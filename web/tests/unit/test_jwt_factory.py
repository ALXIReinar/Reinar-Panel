import jwt
import pytest

from web.utils import jwt_factory


class DummyAuth:
    def __init__(self):
        self.sessions = {}
        self.made_session_args = None
        self.actual_rt = None

    async def make_session(self, session_id, sub, iat, exp, ua, ip, hashed_rT):
        self.made_session_args = (session_id, sub, iat, exp, ua, ip, hashed_rT)
        self.sessions[session_id] = hashed_rT

    async def check_exist_session(self, admin_id, user_agent):
        for s_id in self.sessions:
            return {"session_id": s_id}
        return None

    async def get_actual_rt(self, sub, s_id):
        return self.actual_rt


class DummyDb:
    def __init__(self, auth: DummyAuth):
        self.auth = auth


@pytest.fixture
def jwt_mod(monkeypatch):
    # avoid argon2 backend requirements in tests
    monkeypatch.setattr(jwt_factory.encryption, "hash", lambda x: f"hashed:{x}")
    return jwt_factory


def test_set_and_get_jwt_decode_payload_success(jwt_mod):
    payload = {"foo": "bar"}
    token = jwt_mod.set_jwt_encode(payload)
    decoded = jwt_mod.get_jwt_decode_payload(token)
    assert decoded["foo"] == "bar"


def test_get_jwt_decode_payload_invalid(jwt_mod):
    decoded = jwt_mod.get_jwt_decode_payload("invalid.token.value")
    assert decoded == 401


def test_add_ttl_limit_sets_exp(jwt_mod):
    base = {}
    res = jwt_mod.add_ttl_limit(base, "access_token")
    assert "iat" in res and "exp" in res
    assert res["exp"] > res["iat"]


@pytest.mark.asyncio
async def test_issue_token_refresh(jwt_mod):
    auth = DummyAuth()
    db = DummyDb(auth)
    payload = {"sub": "1"}
    client = type("C", (), {"user_agent": "ua", "ip": "127.0.0.1"})
    hashed_rt = await jwt_mod.issue_token(payload, "refresh_token", db=db, session_id="sess1", client=client)
    assert isinstance(hashed_rt, str) and hashed_rt.startswith("hashed:")
    assert auth.made_session_args[0] == "sess1"


@pytest.mark.asyncio
async def test_issue_token_access_sets_sid(jwt_mod):
    token = await jwt_mod.issue_token({"sub": "1", "role": "r"}, "access_token", session_id="sess2")
    decoded = jwt.decode(token, jwt_mod.env.JWTs.public_key, algorithms=[jwt_mod.env.JWTs.algorithm])
    assert decoded["s_id"] == "sess2"


@pytest.mark.asyncio
async def test_issue_aT_rT_existing_session(jwt_mod):
    auth = DummyAuth()
    auth.sessions["sess-existing"] = "stub-hash"
    db = DummyDb(auth)
    token_schema = type("TS", (), {"id": 1, "user_agent": "ua", "ip": "127.0.0.1"})
    aT, rT = await jwt_mod.issue_aT_rT(db, token_schema)
    decoded = jwt.decode(aT, jwt_mod.env.JWTs.public_key, algorithms=[jwt_mod.env.JWTs.algorithm])
    assert decoded["sub"] == "1"
    assert decoded["s_id"]
    assert isinstance(rT, str) and rT.startswith("hashed:")


@pytest.mark.asyncio
async def test_reissue_aT_success(jwt_mod):
    auth = DummyAuth()
    auth.actual_rt = {"refresh_token": "stored"}
    db = DummyDb(auth)
    access = {"sub": "1", "s_id": "sess3", "role": "methodist"}
    new_at = await jwt_mod.reissue_aT(access, "stored", db)
    decoded = jwt.decode(new_at, jwt_mod.env.JWTs.public_key, algorithms=[jwt_mod.env.JWTs.algorithm])
    assert decoded["sub"] == "1"
    assert decoded["s_id"] == "sess3"


@pytest.mark.asyncio
async def test_reissue_aT_invalid(jwt_mod):
    auth = DummyAuth()
    auth.actual_rt = None
    db = DummyDb(auth)
    access = {"sub": "1", "s_id": "sess3"}
    res = await jwt_mod.reissue_aT(access, "mismatch", db)
    assert res == 401
