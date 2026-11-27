import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .db import Row
from .install import install
from .isolation import PreconditionFailed, Stand, stability_window, unit_name
from .log import logger
from .manifest import ManifestEntry, find
from .manual import InstallContext, build_steps
from .nodeclient_api import NodeClient
from .results import exclusive_run, read_results, record, snapshot, versions
from .stage_s1 import CRITICAL, run_s1
from .stage_s2 import run_s2
from .stage_s15 import run_s15
from .sub_service import SubService


class Runner:
    def __init__(self, stand: Stand, client: NodeClient, sub_service: SubService, root: Path, stamp: str):
        self.stand = stand
        self.client = client
        self.sub_service = sub_service
        self.root = root
        self.stamp = stamp
        self.pending = root / "pending.json"
        self.artifacts: list[dict] = []

    def _remember(self, physical: Row, sub: Row, *, title: str | None = None, node_id: int | None = None) -> None:
        temporary = self.pending.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "physical_id": physical["id"],
                    "sub_id": sub["id"],
                    "title": title,
                    "node_id": node_id,
                }
            ),
            encoding="utf-8",
        )
        temporary.replace(self.pending)

    def _cleanup_pending(self) -> None:
        if not self.pending.exists():
            return
        pending = json.loads(self.pending.read_text(encoding="utf-8"))
        stand = self.stand
        db, cfg = stand.db, stand.cfg
        physical = db.physical_node(cfg.physical_node_title)
        sub = db.subscription(cfg.test_user_id, cfg.test_sub_plan_id)
        if not physical or not sub or pending["physical_id"] != physical["id"] or pending["sub_id"] != sub["id"]:
            raise RuntimeError("Настройки стенда изменились, осталась нода предыдущего прогона")
        if pending["node_id"] is None:
            rows = db.by_run_title(physical["id"], pending["title"])
        else:
            node = db.vnode(pending["node_id"])
            rows = [node] if node else []
        for node in rows:
            template = db.template(node["template"])
            if node["node_id"] != physical["id"] or template is None:
                raise RuntimeError(f"Не подтверждена принадлежность предыдущей ноды {node['id']} стенду")
            if node["service_name"] or node["user_visible"] or db.attached_plans(node["id"]):
                stand.cleanup(node, template, sub)
        self.pending.unlink()

    def _sweep_entries(self, args: argparse.Namespace, entries: list[ManifestEntry]) -> list[ManifestEntry]:
        for title in args.only:
            find(entries, title)
        ordered = sorted(entries, key=lambda item: (item.cdn, item.tls, item.template))
        if args.from_template:
            first = find(ordered, args.from_template)
            ordered = ordered[ordered.index(first) :]
        if args.only:
            ordered = [item for item in ordered if item.template in args.only]
        return [item for item in ordered if not item.skip]

    def run(self, args: argparse.Namespace, entries: list[ManifestEntry]) -> int:
        with exclusive_run(self.root):
            history = read_results(self.root)
            try:
                if args.command == "verify":
                    self._cleanup_pending()
                    return self.verify(args, entries, history)
                targets = self._sweep_entries(args, entries)
                if args.resume and not any(row["run_id"] == args.resume for row in history):
                    raise ValueError(f"Не найден прогон {args.resume}")
                done = {row["template"] for row in history if row["run_id"] == args.resume}
                self._cleanup_pending()
                failed = False
                for entry in targets:
                    if entry.template in done:
                        continue
                    result = self.run_entry(args, entry)
                    if result == 130:
                        return 130
                    if result:
                        failed = True
                        if self.pending.exists() or not args.continue_on_fail:
                            break
                return int(failed)
            finally:
                for artifact in self.artifacts:
                    logger.info("Артефакты — %s", json.dumps(artifact, ensure_ascii=False))

    def verify(self, args: argparse.Namespace, entries: list[ManifestEntry], history: list[dict]) -> int:
        stand = self.stand
        physical = stand.db.physical_node(stand.cfg.physical_node_title)
        if not physical:
            raise PreconditionFailed("Физическая нода отсутствует")
        if args.template:
            template = stand.db.template(args.template)
            node = stand.db.installed(physical["id"], template["id"]) if template else None
        else:
            node = stand.db.vnode(args.node_proto_id)
        if not node or node["node_id"] != physical["id"] or node["reg_status"] != 2:
            raise PreconditionFailed("Зарегистрированная виртуальная нода на стенде не найдена")
        entry = find(entries, node["template"])
        if entry.skip:
            raise PreconditionFailed(f"{entry.template} — {entry.skip}")
        previous = next(
            (
                row
                for row in reversed(history)
                if row.get("node_proto_id") == node["id"]
                and row["template"] == entry.template
                and row["s1"]["status"] == "ok"
            ),
            None,
        )
        if not previous:
            raise PreconditionFailed(f"Нет успешного S1 для ноды {node['id']}")
        return self.run_entry(args, entry, node, previous["s1"])

    def run_entry(
        self,
        args: argparse.Namespace,
        entry: ManifestEntry,
        existing: Row | None = None,
        previous_s1: dict | None = None,
    ) -> int:
        stand = self.stand
        cfg = stand.cfg
        run_id = getattr(args, "resume", None) or self.stamp
        started = datetime.now(UTC)
        directory = self.root / self.stamp / f"install-{uuid4().hex[:12]}"
        result = dict(
            template=entry.template,
            run_id=run_id,
            mode=args.command,
            started=started.isoformat(),
            s1=previous_s1 or {"status": "not_run"},
            s15={"status": "not_run"},
            s2={"status": "not_run"},
            install_script=entry.install_script,
            snapshot=None,
        )
        rows: list[Row] = []
        title = None
        physical = None
        interrupted = False
        keep_running = getattr(args, "keep_running", False)
        logger.info("Шаблон %s", entry.template)
        try:
            confirmed = getattr(args, "confirm_cdn_ready", False)
            interactive = args.command == "verify" or getattr(args, "interactive", False)
            if entry.cdn and not confirmed and interactive:
                confirmed = input("DNS и Cloudflare готовы? [да/нет] ").strip().lower() == "да"
            if entry.cdn and not confirmed:
                result.update(status="skipped", reason="cdn_not_confirmed")
                return 0
            physical, sub = stand.prepare(existing["id"] if existing else None)
            template = stand.db.template(entry.template)
            if not template:
                raise PreconditionFailed("Шаблон отсутствует в БД")
            node = existing
            if existing:
                unit = unit_name(existing)
                self._remember(physical, sub, node_id=existing["id"])
                rows = [existing]
                self.client.reinit(existing["id"])
                stand.os.systemctl("start", unit)
                stable, evidence = stand.os.stable(unit, stability_window(cfg))
                result["verify_stability"] = evidence
                if not stable:
                    raise RuntimeError("Unit нестабилен после запуска")
            else:
                title = f"chk-{template['id']}-{self.stamp[-6:]}"
                steps = build_steps(entry, InstallContext(cfg, template["id"], physical["id"], title))
                self._remember(physical, sub, title=title)
                result["install_reported_id"] = False
                result["install_log_dir"] = str(directory)
                installation = install(steps, directory, cfg.timeouts.install_s)
                result["install_reported_id"] = installation.node_id is not None
                result["cert_paths"] = installation.cert_paths
                rows = stand.db.by_run_title(physical["id"], title)
                node = next(
                    (row for row in rows if row["id"] == installation.node_id and row["tmp_id"] == template["id"]), None
                )
                result["s1"] = run_s1(stand, self.client, entry, installation, node, template, rows)
            result["versions"] = versions(stand, entry, template)
            if node:
                self._set_artifacts(result, node)
            critical = any(
                item["name"] in CRITICAL and item["status"] != "pass" for item in result["s1"].get("checks", [])
            )
            if node and not critical:
                if entry.cdn and node["proto_port"] != 443:
                    raise RuntimeError("CDN-нода не слушает предусмотренный манифестом порт 443")
                result["s15"] = run_s15(stand, self.sub_service, node, template, sub)
                bound_at = datetime.now(UTC)
                if interactive and result["s1"]["status"] == result["s15"]["status"] == "ok":
                    result["s2"] = run_s2(stand, node, sub, run_id, bound_at)
            statuses = {result[key]["status"] for key in ("s1", "s15", "s2")}
            attempts = result["s2"].get("attempts", [])
            rejected = bool(attempts and attempts[-1]["verdict"] == "2")
            if "failed" in statuses or rejected:
                result["status"] = "failed"
            else:
                result["status"] = "inconclusive" if "inconclusive" in statuses else "ok"
        except PreconditionFailed as exc:
            result.update(status="precondition_failed", reason=str(exc))
        except (KeyboardInterrupt, EOFError):
            interrupted = True
            result["status"] = "interrupted"
        except Exception as exc:
            reason = str(exc) if isinstance(exc, (RuntimeError, ValueError)) else type(exc).__name__
            result.update(status="failed", reason=reason)
        finally:
            if title and physical and self.pending.exists() and not rows:
                try:
                    rows = stand.db.by_run_title(physical["id"], title)
                except RuntimeError as exc:
                    logger.error("%s", exc)
            if not result.get("node_proto_id") and len(rows) == 1:
                self._set_artifacts(result, rows[0])
            if result["status"] in {"failed", "inconclusive", "interrupted"}:
                self._snapshot(result, directory, rows)
            if self.pending.exists() and (not keep_running or result["status"] != "ok"):
                try:
                    self._cleanup_pending()
                except (Exception, KeyboardInterrupt) as exc:
                    result["cleanup_error"] = str(exc) or type(exc).__name__
                    result["status"] = "interrupted" if interrupted or isinstance(exc, KeyboardInterrupt) else "failed"
                    self._snapshot(result, directory, rows)
            record(self.root, result)
            logger.info(
                "%s — %s%s", entry.template, result["status"], f" — {result['reason']}" if result.get("reason") else ""
            )
            if result.get("cleanup_error"):
                logger.error("Изоляция не завершена — %s", result["cleanup_error"])
            self.artifacts.extend({key: row.get(key) for key in ("id", "service_name", "config_path")} for row in rows)
            if result.get("cert_paths"):
                self.artifacts.append({"cert_paths": result["cert_paths"]})
        if result["status"] == "interrupted":
            return 130
        return int(result["status"] in {"failed", "precondition_failed"})

    def _snapshot(self, result: dict, directory: Path, rows: list[Row]) -> None:
        try:
            snapshot(self.root, self.stand, result, directory, rows)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("Не удалось сохранить снимок — %s", type(exc).__name__)

    @staticmethod
    def _set_artifacts(result: dict, node: Row) -> None:
        result.update(node_proto_id=node["id"], config_path=node.get("config_path"))
        try:
            result["unit"] = unit_name(node)
        except ValueError:
            pass
