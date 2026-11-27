import re
import shlex
import shutil
import time
from pathlib import Path

from .db import Row
from .install import Installation
from .isolation import Stand, stability_window, unit_name
from .manifest import ManifestEntry
from .node_config import NodeConfig, leaves
from .nodeclient_api import NodeClient

CRITICAL = {"exit_and_stdout", "db_record", "service_name", "unit_stable", "ports"}
CHECKS = (
    "exit_and_stdout",
    "db_record",
    "service_name",
    "config_file",
    "paths_consistent",
    "unit_stable",
    "ports",
    "metrics_script",
    "metrics_binary",
    "reload",
    "tls",
    "states",
    "node_data",
)


def check(name: str, ok: bool, evidence) -> dict:
    return {"name": name, "status": "pass" if ok else "fail", "evidence": evidence}


def stage(checks: list[dict]) -> dict:
    statuses = {item["status"] for item in checks}
    status = "failed" if "fail" in statuses else "inconclusive" if "unverified" in statuses else "ok"
    return {"status": status, "checks": checks}


def check_ports(stand: Stand, node: Row, unit: str) -> tuple[bool, list[str]]:
    pids = stand.os.cgroup_pids(unit)
    listeners = stand.os.listeners()
    proto = [item for item in listeners if item.port == node["proto_port"]]
    metrics = [item for item in listeners if item.port == node["metrics_port"]]
    ok = (
        any(item.pids & pids for item in proto)
        and bool(metrics)
        and all(item.address == "127.0.0.1" and bool(item.pids & pids) for item in metrics)
    )
    return ok, [item.raw for item in [*proto, *metrics]]


def wait_ports(stand: Stand, node: Row, unit: str) -> tuple[bool, list[str]]:
    deadline = time.monotonic() + stand.cfg.timeouts.stability_window_s[1]
    while True:
        ok, sockets = check_ports(stand, node, unit)
        if ok and stand.os.show(unit, "ActiveState").get("ActiveState") == "active":
            return True, sockets
        if time.monotonic() >= deadline:
            return False, sockets
        time.sleep(1)


def run_s1(
    stand: Stand,
    client: NodeClient,
    entry: ManifestEntry,
    installation: Installation,
    node: Row | None,
    template: Row,
    rows: list[Row],
) -> dict:
    returned = installation.returncode == 0 and installation.node_id is not None
    checks = [check("exit_and_stdout", returned, {"code": installation.returncode, "id": installation.node_id})]
    if installation.node_id is None:
        checks.extend(dict(name=name, status="not_run", evidence="Не получен ID ноды") for name in CHECKS[1:])
        return stage(checks)
    fields = ("config_path", "service_name", "proto_port", "metrics_port")
    registered = bool(node and node["reg_status"] == 2 and all(node.get(field) for field in fields))
    checks.append(
        check("db_record", registered, {key: node.get(key) for key in ("reg_status", *fields)} if node else {})
    )
    if not node:
        return stage(checks)
    os = stand.os

    def evaluate(name, operation):
        try:
            ok, evidence = operation()
            checks.append(check(name, ok, evidence))
        except Exception as exc:
            checks.append(check(name, False, str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__))

    try:
        unit = unit_name(node)
        os.systemctl("cat", unit)
        checks.append(check("service_name", unit == installation.unit, unit))
    except (RuntimeError, ValueError) as exc:
        checks.append(check("service_name", False, str(exc)))
        return stage(checks)
    path = node.get("config_path")
    evaluate("config_file", lambda: (isinstance(NodeConfig(node, template).read(), dict), path))
    evaluate(
        "paths_consistent",
        lambda: (
            bool(
                path
                and Path(path).is_file()
                and re.search(rf"(?<!\S){re.escape(path)}(?=\s|;|$)", os.show(unit, "ExecStart")["ExecStart"])
            ),
            path,
        ),
    )

    def stable():
        ok, evidence = os.stable(unit, stability_window(stand.cfg))
        return ok and evidence["after"].get("NRestarts") == "0", evidence

    evaluate("unit_stable", stable)
    evaluate("ports", lambda: check_ports(stand, node, unit))

    def metrics():
        data = client.metrics(node["id"], node["metrics_port"])
        return isinstance(data.get("users_traffic"), list), {
            field: data.get(field) for field in ("users_traffic", "source", "fallback_reason")
        }

    evaluate("metrics_script", metrics)
    command = node.get("metrics_command") or template.get("metrics_command")
    if command:

        def binary():
            executable = shlex.split(command.format(node["metrics_port"]))[0]
            return bool(shutil.which(executable)), executable

        evaluate("metrics_binary", binary)
    else:
        checks.append(dict(name="metrics_binary", status="skipped", evidence="Команда отсутствует"))

    def reload():
        os.run("bash", "-c", node["reload_core_command"])
        return wait_ports(stand, node, unit)

    evaluate("reload", reload)
    if entry.tls:

        def tls():
            paths = installation.cert_paths
            if not paths or not all(value and Path(value).is_file() for value in paths.values()):
                return False, paths
            services = Path(paths["services_list"]).read_text().splitlines()
            if unit not in services:
                return False, paths
            # Та же операция хука для проверяемого unit.
            os.systemctl("try-restart", unit)
            ok, _ = wait_ports(stand, node, unit)
            return ok, paths

        evaluate("tls", tls)
    else:
        checks.append(dict(name="tls", status="skipped", evidence="Шаблон без TLS"))

    def states():
        active = os.show(unit, "ActiveState").get("ActiveState")
        pending = [row["id"] for row in rows if row["reg_status"] != 2]
        return returned and registered and active == "active" and not pending, {"active": active, "pending": pending}

    evaluate("states", states)
    data = node.get("constant_node_data_obj")
    checks.append(check("node_data", all(value not in (None, "") for value in leaves(data)), "Проверены листья JSON"))
    return stage(checks)
