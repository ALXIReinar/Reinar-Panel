import re
import time
from datetime import UTC, datetime

from .config import Config
from .db import Database, Row
from .node_config import NodeConfig
from .osutil import OperatingSystem
from .panel_api import Http, Panel

ANSI = re.compile(r"\x1b\[[0-9;]*m")


class PreconditionFailed(RuntimeError):
    pass


def unit_name(node: Row) -> str:
    name = node.get("service_name")
    if not isinstance(name, str) or not re.fullmatch(rf"reinar-[a-z0-9]+-{node['id']}", name):
        raise ValueError(f"Некорректное имя unit для ноды {node['id']}")
    return name


def stability_window(cfg: Config) -> int:
    low, high = cfg.timeouts.stability_window_s
    return (low + high) // 2


class Stand:
    def __init__(self, cfg: Config, db: Database, panel: Panel, os: OperatingSystem):
        self.cfg = cfg
        self.db = db
        self.panel = panel
        self.os = os

    def prepare(self, node_id: int | None = None) -> tuple[Row, Row]:
        cfg = self.cfg
        physical = self.db.physical_node(cfg.physical_node_title)
        if not physical or not physical["is_active"]:
            raise PreconditionFailed("Физическая нода отсутствует или не активна")
        sub = self.db.subscription(cfg.test_user_id, cfg.test_sub_plan_id)
        if not sub or not sub["is_active"] or not sub["plan_active"]:
            raise PreconditionFailed("Тестовая подписка или план отсутствуют либо не активны")
        foreign_ids = {row["id"] for row in self.db.visible_nodes(physical["id"])}
        foreign_ids.update(self.db.plan_vnodes(cfg.test_sub_plan_id))
        foreign_ids.discard(node_id)
        if foreign_ids:
            raise PreconditionFailed(f"Другие видимые ноды или локации тестового плана — {sorted(foreign_ids)}")
        for other in self.db.node_units(physical["id"]):
            if other["id"] == node_id or not other["service_name"]:
                continue
            state = self.os.show(other["service_name"], "ActiveState").get("ActiveState")
            if state in {"active", "activating", "reloading", "deactivating"}:
                raise PreconditionFailed(f"Другая нода ещё работает — {other['id']}, {other['service_name']}")
        selected = self.db.vnode(node_id) if node_id is not None else None
        allowed_pids = self.os.cgroup_pids(unit_name(selected)) if selected else set()
        occupied = [
            listener.raw
            for listener in self.os.listeners()
            if listener.port in cfg.required_free_ports and (not listener.pids or not listener.pids <= allowed_pids)
        ]
        if occupied:
            raise PreconditionFailed("Заняты порты:\n" + "\n".join(occupied))
        http = Http(cfg.timeouts.http_s)
        try:
            for url in dict.fromkeys((cfg.install_admin_url, cfg.admin_url, cfg.sub_service_url)):
                http.request("GET", url, "/")
        except RuntimeError as exc:
            raise PreconditionFailed(str(exc)) from None
        finally:
            http.close()
        return physical, sub

    def cleanup(self, node: Row, template: Row, sub: Row) -> None:
        node_id = node["id"]
        unit = unit_name(node)
        plans = self.db.attached_plans(node_id)
        plan_id = self.cfg.test_sub_plan_id
        if set(plans) - {plan_id}:
            raise RuntimeError(f"Нода {node_id} используется в других планах")
        # Привязка могла уже исчезнуть из БД, пока фоновая задача ещё меняет конфиг.
        if node["user_visible"] or plan_id in plans:
            started = datetime.now(UTC)
            config = NodeConfig(node, template)
            previous, _ = config.wait_user(sub, False, 0)
            if plan_id in plans:
                if not node["user_visible"] or self.os.show(unit, "ActiveState").get("ActiveState") != "active":
                    raise RuntimeError(f"Для отвязки ноды {node_id} требуется работающий видимый unit")
                self.panel.remove_vnode(plan_id, node_id)
            timeout = self.cfg.timeouts.unbind_wait_s
            data, waited = config.wait_user(sub, False, timeout)
            if data is None:
                raise RuntimeError(f"Пользователь остался в конфиге ноды {node_id}")
            if previous is None:
                self._wait_applied(node_id, unit, started, max(0, timeout - waited))
            if self.db.attached_plans(node_id):
                raise RuntimeError(f"Не подтверждена отвязка ноды {node_id}")
            if node["user_visible"]:
                self.panel.set_visible(node_id, False)
        self.os.systemctl("stop", unit)
        self.os.systemctl("disable", unit)

    def _wait_applied(self, node_id: int, unit: str, started: datetime, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        written = re.compile(rf"Успешная запись \| node_proto_id: {node_id}\b")
        while True:
            journal = ANSI.sub("", self.os.journal(self.cfg.node_client_unit, started))
            if written.search(journal) and self.os.show(unit, "ActiveState").get("ActiveState") == "active":
                return
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Журнал нод-клиента не подтвердил удаление пользователя с ноды {node_id}")
            time.sleep(1)
