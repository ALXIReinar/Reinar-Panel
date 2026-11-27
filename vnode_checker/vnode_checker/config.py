from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
CORE_BINARIES = {"xray": "/usr/local/bin/xray", "singbox": "/usr/local/bin/sing-box"}


@dataclass(frozen=True)
class Timeouts:
    http_s: int = 15
    db_s: int = 15
    os_s: int = 15
    bind_wait_s: int = 10
    stability_window_s: tuple[int, int] = (10, 15)
    unbind_wait_s: int = 30
    collector_interval_s: int = 300
    collector_grace_s: int = 60
    s2_poll_interval_s: int = 5
    install_s: int = 600

    def __post_init__(self):
        low, high = self.stability_window_s
        for name, value in vars(self).items():
            if name != "stability_window_s":
                positive(value, f"timeouts.{name}")
        positive(low, "timeouts.stability_window_s")
        positive(high, "timeouts.stability_window_s")
        if high < low:
            raise ValueError("Неверный диапазон stability_window_s")


def positive(value: Any, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"Ожидалось целое положительное значение {name}")


@dataclass(frozen=True)
class Config:
    db_env_file: Path
    scripts_root: Path
    physical_node_title: str
    test_user_id: int
    test_sub_plan_id: int
    admin_url: str = "http://127.0.0.1:8000"
    sub_service_url: str = "http://127.0.0.1:18080"
    node_client_url: str = "http://127.0.0.1:8200"
    node_client_unit: str = "reinar-node"
    admin_panel_ip_for_scripts: str = "10.0.0.1"
    admin_panel_port_for_scripts: int = 8000
    host_override: str | None = None
    port_override: int | None = None
    domain: str | None = None
    email: str | None = None
    required_free_ports: tuple[int, ...] = (80, 443)
    collector_log_args: tuple[str, ...] = ("docker", "logs", "arq-sub-worker")
    timeouts: Timeouts = Timeouts()

    def __post_init__(self):
        for key in ("test_user_id", "test_sub_plan_id"):
            positive(getattr(self, key), key)
        for port in (*self.required_free_ports, self.admin_panel_port_for_scripts, self.port_override or 5432):
            positive(port, "порт")
            if port > 65535:
                raise ValueError("Порт вне диапазона 1–65535")
        for url in (self.admin_url, self.sub_service_url, self.node_client_url, self.install_admin_url):
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None:
                raise ValueError("Ожидался HTTP(S) URL без учётных данных")
        if not self.physical_node_title or not self.collector_log_args:
            raise ValueError("Задайте physical_node_title и collector_log_args")

    @property
    def install_admin_url(self) -> str:
        host = self.admin_panel_ip_for_scripts
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"http://{host}:{self.admin_panel_port_for_scripts}"

    def db_connection_params(self) -> dict:
        """Читает параметры PostgreSQL без выполнения или интерполяции файла."""
        with self.db_env_file.open(encoding="utf-8") as file:
            data = dotenv_values(stream=file, interpolate=False)
        params = {
            "user": data.get("PG_USER"),
            "password": data.get("PG_PASSWORD"),
            "dbname": data.get("PG_DB"),
            "host": self.host_override or data.get("PG_HOST"),
            "port": str(self.port_override or data.get("PG_PORT") or 5432),
        }
        missing = [name for name, value in params.items() if not value]
        if missing:
            raise ValueError(f"В настройках PostgreSQL отсутствуют поля {', '.join(missing)}")
        return params


def load_config(path: Path) -> Config:
    path = path.resolve()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        db = raw.pop("db")
        timeouts = Timeouts(**raw.pop("timeouts", {}))
        scripts_root = raw.pop("scripts_root", "../node_client/scripts")
        return Config(
            db_env_file=(path.parent / db["env_file"]).resolve(),
            scripts_root=(path.parent / scripts_root).resolve(),
            host_override=db.get("host_override"),
            port_override=db.get("port_override"),
            timeouts=timeouts,
            **raw,
        )
    except (AttributeError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise ValueError(f"Некорректные настройки в {path} ({type(exc).__name__})") from None
