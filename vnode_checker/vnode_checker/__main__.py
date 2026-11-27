import argparse
import os
import sys
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml

from . import manifest
from .config import ROOT, Config, load_config
from .db import Database
from .log import configure_log, logger
from .manual import InstallContext, build_steps, render_manual
from .nodeclient_api import NodeClient
from .panel_api import Http, Panel


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Проверка шаблонов виртуальных нод")
    parser.add_argument("--config", type=Path, default=ROOT / "checker.yaml")
    parser.add_argument("--manifest", type=Path, default=ROOT / "manifest.yaml")
    commands = parser.add_subparsers(dest="command", required=True)
    manifest_commands = commands.add_parser("manifest", help="Управление манифестом")
    operations = manifest_commands.add_subparsers(dest="operation", required=True)
    generate = operations.add_parser("generate", help="Добавить новые шаблоны из PostgreSQL")
    generate.add_argument("--no-prompt", action="store_true")
    operations.add_parser("lint", help="Проверить манифест")
    manual_commands = commands.add_parser("manual", help="Инструкции по установке")
    manual = manual_commands.add_subparsers(dest="operation", required=True)
    print_manual = manual.add_parser("print", help="Вывести команды установки")
    print_manual.add_argument("template")
    sweep = commands.add_parser("sweep", help="Последовательно проверить шаблоны")
    sweep.add_argument("--only", action="append", default=[])
    sweep.add_argument("--from", dest="from_template")
    sweep.add_argument("--resume")
    sweep.add_argument("--continue-on-fail", action="store_true")
    sweep.add_argument("--interactive", action="store_true")
    sweep.add_argument("--confirm-cdn-ready", action="store_true")
    verify = commands.add_parser("verify", help="Проверить подключение с телефона")
    selected = verify.add_mutually_exclusive_group(required=True)
    selected.add_argument("--template")
    selected.add_argument("--node-proto-id", type=int)
    verify.add_argument("--confirm-cdn-ready", action="store_true")
    verify.add_argument("--keep-running", action="store_true")
    report = commands.add_parser("report", help="Отчёты по результатам")
    report.add_subparsers(dest="operation", required=True).add_parser("coverage", help="Непокрытые install-скрипты")
    return parser.parse_args()


def run(args: argparse.Namespace, cfg: Config, panel: Panel, node_client: NodeClient, stamp: str) -> int:
    db = Database(cfg)
    if args.command == "report":
        from .report import uncovered

        for script in uncovered(ROOT / "runs", cfg.scripts_root):
            print(script)
        return 0
    if args.command in {"sweep", "verify"}:
        from .isolation import Stand
        from .osutil import OperatingSystem
        from .runner import Runner
        from .sub_service import SubService

        entries = manifest.load(args.manifest)
        if len({entry.template for entry in entries}) != len(entries):
            raise ValueError("Манифест содержит повторяющиеся шаблоны")
        sub_http = Http(cfg.timeouts.http_s)
        try:
            stand = Stand(cfg, db, panel, OperatingSystem(cfg.timeouts.os_s))
            service = SubService(cfg.sub_service_url, sub_http)
            return Runner(stand, node_client, service, ROOT / "runs", stamp).run(args, entries)
        finally:
            sub_http.close()
    if args.command == "manifest":
        titles = db.template_titles()
        if args.operation == "generate":
            added, stale = manifest.generate(args.manifest, titles, cfg.scripts_root, args.no_prompt)
            logger.info("Добавлено шаблонов — %d", len(added))
            for row in added:
                logger.info("%s — %s", row["template"], row["skip"] or row["install_script"])
            for title in stale:
                logger.warning("Шаблон отсутствует в БД — %s", title)
            return 0
        errors, warnings = manifest.lint(manifest.load(args.manifest), set(titles), cfg)
        for warning in warnings:
            logger.warning("%s", warning)
        for error in errors:
            logger.error("%s", error)
        if not errors:
            logger.info("Манифест прошёл проверку")
        return int(bool(errors))

    entry = manifest.find(manifest.load(args.manifest), args.template)
    template = db.template(entry.template)
    if template is None:
        raise ValueError(f"Шаблон отсутствует в БД — {entry.template}")
    node = db.physical_node(cfg.physical_node_title)
    if node is None:
        raise ValueError(f"Физическая нода отсутствует в БД — {cfg.physical_node_title}")
    title = f"chk-{template['id']}-{uuid4().hex[:6]}"
    print(render_manual(build_steps(entry, InstallContext(cfg, template["id"], node["id"], title))))
    return 0


def main() -> int:
    args = parse_args()
    if os.geteuid() != 0:
        print("Запустите vnode_checker от root", file=sys.stderr)
        return 2
    os.umask(0o077)
    stamp = f"{datetime.now(UTC):%Y-%m-%dT%H-%M-%S}_{uuid4().hex[:6]}"
    try:
        configure_log(ROOT / "runs" / stamp / "checker.log")
        cfg = load_config(args.config)
        if args.command in {"sweep", "verify", "report"}:
            # При запуске из vnode_checker/ исходники общего компилятора находятся уровнем выше.
            sys.path.insert(0, str(ROOT.parent))
        with ExitStack() as stack:
            panel = Panel(cfg)
            stack.callback(panel.close)
            node_http = Http(cfg.timeouts.http_s)
            stack.callback(node_http.close)
            node_client = NodeClient(cfg.node_client_url, node_http)
            panel.check_startup()
            node_client.check_reinit()
            return run(args, cfg, panel, node_client, stamp)
    except (OSError, RuntimeError, TypeError, ValueError, yaml.YAMLError) as exc:
        logger.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        logger.info("Выполнение прервано")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
