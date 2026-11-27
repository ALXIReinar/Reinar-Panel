import re
import time
from contextlib import contextmanager
from datetime import UTC, datetime

from .db import Row
from .isolation import ANSI, Stand, stability_window, unit_name
from .log import logger


@contextmanager
def packet_rules(stand: Stand, port: int, run_id: str):
    comment = f"vnode-checker-{run_id}"
    installed = []
    complete = True
    try:
        for command in ("iptables", "ip6tables"):
            for protocol in ("tcp", "udp"):
                rule = ("-p", protocol, "--dport", str(port), "-m", "comment", "--comment", comment)
                installed.append((command, rule))
                try:
                    stand.os.run(command, "-w", "-I", "INPUT", "1", *rule)
                except RuntimeError:
                    complete = False
                    try:
                        exists = stand.os.run(command, "-w", "-C", "INPUT", *rule, check=False).returncode == 0
                    except RuntimeError:
                        exists = False
                    if not exists:
                        installed.pop()
        yield comment if complete else None
    finally:
        failures = []
        for command, rule in reversed(installed):
            try:
                stand.os.run(command, "-w", "-D", "INPUT", *rule)
            except RuntimeError:
                try:
                    absent = stand.os.run(command, "-w", "-C", "INPUT", *rule, check=False).returncode == 1
                except RuntimeError:
                    absent = False
                if not absent:
                    failures.append(f"{command} {rule[1]}")
        if failures:
            raise RuntimeError(f"Не удалось снять счётчики {comment}: {', '.join(failures)}")


def read_packets(stand: Stand, comment: str | None) -> dict | None:
    if not comment:
        return None
    counts = {}
    for command in ("iptables", "ip6tables"):
        try:
            output = stand.os.run(command, "-w", "-nvxL", "INPUT").stdout
            rows = [line.split() for line in output.splitlines() if f"/* {comment} */" in line]
            if len(rows) != 2:
                return None
            counts[command] = sum(int(row[0]) for row in rows)
        except (RuntimeError, ValueError):
            return None
    return counts


def collector_tick(stand: Stand, node_id: int, after: datetime) -> str | None:
    command = stand.cfg.collector_log_args
    # docker logs принимает RFC3339 и добавляет UTC-время к каждой строке.
    output = stand.os.run(*command, "--timestamps", "--since", after.isoformat())
    pattern = re.compile(rf"(?:Метрики обновлены|Нет данных для обновления) \| node_proto_id: {node_id}\b")
    for line in reversed((output.stdout + "\n" + output.stderr).splitlines()):
        if pattern.search(ANSI.sub("", line)):
            stamp = line.split(maxsplit=1)[0]
            try:
                if datetime.fromisoformat(stamp) >= after:
                    return stamp
            except ValueError:
                continue
    return None


def interpret(verdict: str, delta: int, packets: bool | None, confirmed: bool) -> str:
    if delta < 0 or delta == 0 and not confirmed:
        return "inconclusive"
    if verdict == "1":
        if delta == 0:
            return "anomaly"
        if packets:
            return "PASS"
    if verdict == "2":
        if delta == 0:
            if packets is not None:
                return "connection_failed" if packets else "blocked_or_not_attempted"
        elif packets:
            return "routing_or_outbound"
    return "inconclusive"


def run_s2(stand: Stand, node: Row, sub: Row, run_id: str, bound_at: datetime) -> dict:
    cfg = stand.cfg
    unit = unit_name(node)
    node_id = node["id"]
    latest = stand.db.vnode(node_id)
    if not latest or not latest["user_visible"] or stand.db.plan_vnodes(cfg.test_sub_plan_id) != [node_id]:
        raise RuntimeError("Для S2 требуется единственная видимая нода тестового плана")
    timeout = cfg.timeouts.collector_interval_s + cfg.timeouts.collector_grace_s
    attempts: list[dict] = []
    while True:
        deadline = time.monotonic() + timeout
        while not (initial := collector_tick(stand, node_id, bound_at)):
            if time.monotonic() >= deadline:
                return dict(
                    status="inconclusive", reason="Штатный сбор после привязки не подтверждён", attempts=attempts
                )
            time.sleep(cfg.timeouts.s2_poll_interval_s)
        baseline = stand.panel.subscription_usage(cfg.test_user_id, sub["id"])
        state = stand.os.show(unit, "ActiveState", "MainPID")
        pid = state.get("MainPID")
        if state.get("ActiveState") != "active" or not int(pid or 0):
            raise RuntimeError("Для S2 требуется активный unit")

        with packet_rules(stand, node["proto_port"], run_id) as comment:
            print(
                f"Готово к проверке — {node['title']}. Обновите подписку, выберите локацию, подключитесь, "
                "откройте заблокированный ресурс и передайте не менее 10 МБ за 15–20 секунд."
            )
            verdict = ""
            while verdict not in {"1", "2", "3", "4", "5"}:
                verdict = input("1 — ок, 2 — провал, 3 — другая сеть, 4 — рестарт, 5 — пропуск: ").strip()
            entered = datetime.now(UTC)
            attempt = dict(
                verdict=verdict,
                note=input("Заметка: "),
                network=input("Сеть: "),
                baseline=baseline,
                initial_tick=initial,
                main_pid_before=pid,
            )
            attempts.append(attempt)
            if verdict in {"1", "2", "3"}:
                deadline = time.monotonic() + timeout
                while True:
                    tick = collector_tick(stand, node_id, entered)
                    usage = stand.panel.subscription_usage(cfg.test_user_id, sub["id"])
                    if tick or usage > baseline or time.monotonic() >= deadline:
                        break
                    time.sleep(cfg.timeouts.s2_poll_interval_s)
                after = stand.os.show(unit, "MainPID").get("MainPID")
                counts = read_packets(stand, comment)
                packets = None if counts is None else sum(counts.values()) > 0
                delta = usage - baseline
                attempt.update(
                    usage=usage,
                    delta=delta,
                    collector_tick=tick,
                    l0=counts,
                    l0_status="unverified" if counts is None else "pass",
                    main_pid_after=after,
                    delta_valid=after == pid,
                )
        if verdict == "5":
            return dict(status="not_run", interpretation="not_checked", attempts=attempts)
        if verdict == "4":
            bound_at = datetime.now(UTC)
            stand.os.systemctl("restart", unit)
            stable, evidence = stand.os.stable(unit, stability_window(cfg))
            attempt["restart"] = evidence
            if not stable:
                return dict(status="failed", reason="Unit нестабилен после перезапуска", attempts=attempts)
            continue
        if verdict == "3":
            logger.info("Повтор проверки в другой сети")
            continue
        outcome = interpret(verdict, delta, packets, tick is not None) if after == pid else "inconclusive"
        status = "ok" if outcome == "PASS" else "inconclusive" if outcome == "inconclusive" else "failed"
        return dict(status=status, interpretation=outcome, attempts=attempts)
