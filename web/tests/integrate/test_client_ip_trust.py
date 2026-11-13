"""
Определение IP клиента и доступ без JWT (бэклог E1)

Тестируем:
- X-Forwarded-For учитывается только от доверенного прокси (TRUSTED_PROXIES); клиент — самый правый адрес цепочки,
  не являющийся прокси (левые подставляет кто угодно)
- поддельный X-Forwarded-For не даёт ни полного доступа (ALLOWED_IPS), ни служебных маршрутов /api/v1/server/*
- нод-клиенты из приватной сети (NODES_PRIVATE_NETWORK) получают только /api/v1/server/*, остальная админка — по JWT
"""

from ipaddress import ip_network

import httpx
import pytest
from fastapi import FastAPI
from starlette.requests import Request

from web.api.middleware import ASGILoggingMiddleware, AuthUXASGIMiddleware
from web.config_dir.config import env
from web.utils.anything import get_client_ip, get_client_ip_by_scope

CADDY = "127.0.0.1"  # caddy на том же хосте (network_mode: host) — доверенный прокси


@pytest.fixture
def trust_settings(monkeypatch):
    """Настройки как у install.sh: прокси и полный доступ — localhost и админка в WG, ноды — 10.0.0.0/24"""
    monkeypatch.setattr(env, "trusted_proxies", {CADDY, "10.0.0.1"})
    monkeypatch.setattr(env, "allowed_ips", {"127.0.0.1", "10.0.0.1"})
    monkeypatch.setattr(env, "nodes_private_network", [ip_network("10.0.0.0/24")])


def make_scope(peer: str | None, xff: str | None = None) -> dict:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return {"type": "http", "headers": headers, "client": (peer, 5555) if peer else None}


# ========== Определение IP клиента ==========


@pytest.mark.parametrize(
    ("peer", "xff", "expected"),
    [
        ("8.8.8.8", "127.0.0.1", "8.8.8.8"),  # подделка напрямую на порт админки — заголовок игнорируется
        ("8.8.8.8", None, "8.8.8.8"),
        (CADDY, "8.8.8.8", "8.8.8.8"),  # через caddy — реальный адрес клиента
        (CADDY, "127.0.0.1, 8.8.8.8", "8.8.8.8"),  # подделанный левый адрес за прокси не помогает
        (CADDY, "10.0.0.1, 127.0.0.1", "10.0.0.1"),  # вся цепочка из прокси — берём исходный адрес
        (CADDY, None, CADDY),  # локальный скрипт без прокси
        (None, "127.0.0.1", "unknown"),
    ],
)
def test_client_ip_trusts_xff_only_from_proxies(trust_settings, peer, xff, expected):
    assert get_client_ip_by_scope(make_scope(peer, xff)) == expected
    if peer:
        assert get_client_ip(Request(make_scope(peer, xff))) == expected


# ========== Доступ без JWT ==========


@pytest.fixture
def app_with_auth():
    app = FastAPI()

    @app.get("/api/v1/private/hello")
    async def private_hello():
        return {"ok": True}

    @app.post("/api/v1/server/nodes/{node_title}/startup")
    async def startup(node_title: str):
        return {"ok": True}

    app.add_middleware(AuthUXASGIMiddleware)
    app.add_middleware(ASGILoggingMiddleware)
    return app


async def call(app: FastAPI, peer: str, method: str, url: str, xff: str | None = None) -> int:
    """Запрос от заданного адреса TCP-соединения (без cookie с JWT)"""
    transport = httpx.ASGITransport(app=app, client=(peer, 5555))
    headers = {"X-Forwarded-For": xff} if xff else {}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        return (await ac.request(method, url, headers=headers)).status_code


STARTUP = "/api/v1/server/nodes/nl-main/startup"
PRIVATE = "/api/v1/private/hello"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("peer", "method", "url", "xff", "status"),
    [
        # Подделка X-Forwarded-For напрямую на порт админки
        ("8.8.8.8", "GET", PRIVATE, "127.0.0.1", 401),
        ("8.8.8.8", "POST", STARTUP, "127.0.0.1", 401),
        ("8.8.8.8", "POST", STARTUP, "10.0.0.5", 401),
        # Внешний клиент через caddy — как внешний, а не как localhost
        (CADDY, "GET", PRIVATE, "8.8.8.8", 401),
        # Нод-клиент из приватной сети: служебные маршруты — да, остальная админка — нет
        ("10.0.0.5", "POST", STARTUP, None, 200),
        ("10.0.0.5", "GET", PRIVATE, None, 401),
        # Адрес вне приватной сети нод
        ("10.0.1.5", "POST", STARTUP, None, 401),
        # Локальные скрипты админки и ALLOWED_IPS — как раньше
        ("127.0.0.1", "POST", STARTUP, None, 200),
        ("10.0.0.1", "GET", PRIVATE, None, 200),
    ],
)
async def test_access_without_jwt(trust_settings, app_with_auth, peer, method, url, xff, status):
    assert await call(app_with_auth, peer, method, url, xff) == status
