import httpx
import jwt
import pytest
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Response
from starlette.requests import Request

from web.api.middleware import AuthUXASGIMiddleware, ASGILoggingMiddleware
from web.config_dir.config import env
from web.schemas.cookie_settings_schema import JWTCookieDep




def _headers_with_ip(ip: str) -> dict[str, str]:
    return {"X-Forwarded-For": ip}


def _expired_access_token(sub: str, session_id: str) -> str:
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    payload = {
        "sub": sub,
        "s_id": session_id,
        "iat": int(past.timestamp()) - 100,
        "exp": int(past.timestamp()),
    }
    return jwt.encode(payload, env.JWTs.private_key, algorithm=env.JWTs.algorithm)


def _valid_access_token(sub: str, session_id: str) -> str:
    now = datetime.now(timezone.utc)
    future = now + timedelta(hours=1)
    payload = {
        "sub": sub,
        "s_id": session_id,
        "iat": int(now.timestamp()),
        "exp": int(future.timestamp()),
    }
    return jwt.encode(payload, env.JWTs.private_key, algorithm=env.JWTs.algorithm)


@pytest.fixture
async def mw_client(pg_pool, seed_info, monkeypatch):
    app = FastAPI()

    @app.get("/api/v1/private/hello")
    async def private_hello(request: Request):
        return {"ok": True, "new_token": bool(getattr(request.state, "new_a_t", None))}

    @app.get("/api/v1/public/hello")
    async def public_hello():
        return {"ok": True}

    @app.get("/api/v1/private/with-di")
    async def private_with_di(response: Response, _: JWTCookieDep):
        set_cookie = "set-cookie" in response.headers
        return {"ok": True, "set_cookie": set_cookie}

    app.add_middleware(AuthUXASGIMiddleware)
    app.add_middleware(ASGILoggingMiddleware)
    app.state.pg_pool = pg_pool

    async with pg_pool.acquire() as conn:
        now_dt = datetime.now(timezone.utc).replace(tzinfo=None)
        exp_dt = now_dt + timedelta(hours=1)
        await conn.execute(
            """
            INSERT INTO sessions_admins (session_id, admin_id, iat, exp, refresh_token, user_agent, ip)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (session_id) DO UPDATE SET iat=$3, exp=$4, refresh_token=$5, ip=$7
            """,
            "sess1",
            seed_info["admin_id"],
            now_dt,
            exp_dt,
            "valid_rt",
            "ua",
            "8.8.8.8",
        )

    async def fake_get_actual_rt(self, admin_id: int, session_id: str):
        return {"refresh_token": "valid_rt"}

    monkeypatch.setattr(
        "web.data.sql_queries.admins_sql.AuthQueries.get_actual_rt",
        fake_get_actual_rt,
        raising=False,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_allowed_ip_passes_without_auth(mw_client):
    valid_at = _valid_access_token("1", "sess1")
    cookies = {"access_token": valid_at}
    resp = await mw_client.get("/api/v1/private/hello", headers=_headers_with_ip("127.0.0.1"), cookies=cookies)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_public_url_allows_without_tokens(mw_client):
    resp = await mw_client.get("/api/v1/public/hello", headers=_headers_with_ip("8.8.8.8"))
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_invalid_access_token_returns_401(mw_client):
    cookies = {"access_token": "invalid"}
    resp = await mw_client.get("/api/v1/private/hello", headers=_headers_with_ip("8.8.8.8"), cookies=cookies)
    assert resp.status_code == 401
    assert resp.json().get("message") == "Нужна повторная аутентификация"


@pytest.mark.asyncio
async def test_expired_access_token_reissued_with_valid_refresh(mw_client, seed_info):
    expired_at = _expired_access_token(str(seed_info["admin_id"]), "sess1")
    cookies = {"access_token": expired_at, "refresh_token": "valid_rt"}
    resp = await mw_client.get("/api/v1/private/hello", headers=_headers_with_ip("8.8.8.8"), cookies=cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["new_token"] is True


@pytest.mark.asyncio
async def test_expired_access_token_with_invalid_refresh_401(mw_client, seed_info):
    expired_at = _expired_access_token(str(seed_info["admin_id"]), "sess1")
    cookies = {"access_token": expired_at, "refresh_token": "bad_refresh"}
    resp = await mw_client.get("/api/v1/private/hello", headers=_headers_with_ip("8.8.8.8"), cookies=cookies)
    assert resp.status_code == 401
    assert resp.json().get("message") == "Нужна повторная аутентификация"


@pytest.mark.asyncio
async def test_di_sets_cookie_on_reissue(mw_client, seed_info):
    expired_at = _expired_access_token(str(seed_info["admin_id"]), "sess1")
    cookies = {"access_token": expired_at, "refresh_token": "valid_rt"}
    resp = await mw_client.get("/api/v1/private/with-di", headers=_headers_with_ip("8.8.8.8"), cookies=cookies)
    assert resp.status_code == 200
    assert "access_token" in resp.cookies
    assert resp.json()["set_cookie"] is True


@pytest.mark.asyncio
async def test_di_does_not_set_cookie_when_token_valid(mw_client):
    valid_at = _valid_access_token("1", "sess1")
    cookies = {"access_token": valid_at}
    resp = await mw_client.get("/api/v1/private/with-di", headers=_headers_with_ip("8.8.8.8"), cookies=cookies)
    assert resp.status_code == 200
    assert "access_token" not in resp.cookies
    assert resp.json()["set_cookie"] is False