"""
IP клиента в логах сервиса подписок (тот же принцип, что в админке — бэклог E1)

X-Forwarded-For учитывается только от доверенного прокси (TRUSTED_PROXIES, caddy), а клиент — самый правый адрес
цепочки, не являющийся прокси: левые адреса подставляет сам клиент.
"""

import pytest
from starlette.requests import Request

from web.sub.config_dir.config import env
from web.sub.config_dir.logger_config import get_client_ip

CADDY = "127.0.0.1"


def make_request(peer: str | None, xff: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request({"type": "http", "headers": headers, "client": (peer, 5555) if peer else None})


@pytest.mark.parametrize(
    ("peer", "xff", "expected"),
    [
        ("8.8.8.8", "1.1.1.1", "8.8.8.8"),  # напрямую на порт сервиса — заголовок игнорируется
        (CADDY, "8.8.8.8", "8.8.8.8"),  # через caddy — реальный адрес клиента
        (CADDY, "1.1.1.1, 8.8.8.8", "8.8.8.8"),  # подделанный левый адрес за прокси не помогает
        (CADDY, "127.0.0.1", "127.0.0.1"),  # вся цепочка из прокси — исходный адрес
        (CADDY, None, CADDY),
        (None, "1.1.1.1", "unknown"),  # без адреса соединения — не падаем
    ],
)
def test_get_client_ip(monkeypatch, peer, xff, expected):
    monkeypatch.setattr(env, "trusted_proxies", {CADDY})
    assert get_client_ip(make_request(peer, xff)) == expected
