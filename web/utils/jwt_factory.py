import secrets
from datetime import datetime, UTC
from uuid import uuid4

import jwt

from typing import Any

from jwt import DecodeError, ExpiredSignatureError

from web.config_dir.config import env, encryption
from web.data.postgres import PgSqlDep
from web.schemas.admins_schema import TokenPayloadSchema
from web.utils.anything import token_types, TokenTypes
from web.utils.logger_config import log_event


def set_jwt_encode(payload: dict[str, Any]):
    encoded = jwt.encode(
        payload=payload,
        key=env.JWTs.private_key,
        algorithm=env.JWTs.algorithm
    )
    return encoded

def get_jwt_decode_payload(encoded_jwt: str, public_key: str | None=None, verify_exp: bool=False, audience: str | None=None):
    try:
        decoded = jwt.decode(
            jwt=encoded_jwt,
            key=public_key or env.JWTs.public_key,
            algorithms=[env.JWTs.algorithm],
            audience=audience,
            options={'verify_exp': verify_exp},
            leeway=10
        )
    except DecodeError:
        decoded = 401
    except ExpiredSignatureError:
        decoded = 401
    return decoded



def add_ttl_limit(data: dict, token_ttl: str):
    created_at = datetime.now(UTC)
    # created_at = datetime.utcnow()
    
    ttl = env.JWTs.ttl_aT
    if token_types[token_ttl] == TokenTypes.refresh_token:
        ttl = env.JWTs.ttl_rT
    elif token_types[token_ttl] == TokenTypes.ws_token:
        ttl = env.JWTs.ttl_wT
    expired_at = created_at + ttl

    data.update(
        iat=created_at,
        exp=expired_at
    )
    return data


async def issue_token(
        payload: dict,
        token: TokenTypes | str,
        db: PgSqlDep = None,
        session_id: str | None=None,
        client: TokenPayloadSchema=None
):
    if token_types[token] == TokenTypes.refresh_token:
        rT = add_ttl_limit(payload, token)
        encoded_rT = set_jwt_encode(rT)
        hashed_rT = encryption.hash(encoded_rT)
        await db.auth.make_session(session_id, int(payload['sub']), rT['iat'], rT['exp'], client.user_agent, client.ip, hashed_rT)
        return hashed_rT
    elif token_types[token] == TokenTypes.access_token:
        payload['s_id'] = session_id if not payload.get('s_id') else payload['s_id']
        aT = add_ttl_limit(payload, token)
        return set_jwt_encode(aT)
    wT = add_ttl_limit(payload, token)
    return set_jwt_encode(wT)




async def issue_aT_rT(db: PgSqlDep, token_schema: TokenPayloadSchema):
    session_id = await db.auth.check_exist_session(token_schema.id, token_schema.user_agent)
    if session_id:
        session_id = session_id['session_id']
        log_event('Существующая сессия: user_id: %s; s_id: %s; ip: %s', token_schema.id, session_id, token_schema.ip)
    else:
        session_id = str(uuid4())
        log_event('Новая сессия | user_id: %s; user_agent: %s; ip: %s',
                  token_schema.id, token_schema.user_agent, token_schema.ip)


    frame_token = {
        'sub': str(token_schema.id),
        'role': token_schema.role,
        'bid': str(token_schema.building_id),
    }
    hashed_rT = await issue_token(frame_token, 'refresh_token', db=db, session_id=session_id, client=token_schema)
    encoded_aT = await issue_token(frame_token, 'access_token', session_id=session_id)
    log_event('Выданы aT, rT токены для %s', repr(token_schema), level='WARNING')
    return encoded_aT, hashed_rT


async def reissue_aT(access_token: dict, refresh_token: str, db: PgSqlDep):
    sub, s_id, role, bid = access_token.get('sub'), access_token.get('s_id'), access_token.get('role'), access_token.get('bid')
    if s_id is None or sub is None:
        return 401

    db_rT = await db.auth.get_actual_rt(int(sub), access_token['s_id'])

    if db_rT and secrets.compare_digest(db_rT['refresh_token'], refresh_token):
        # рефреш_токен СОВПАЛ с выданным и ещё НЕ ИСТЁК
        log_event(f"Выпущен новый access_token | s_id: {s_id}; user_id: {sub}")
        new_access_token = await issue_token(
            {'sub': sub, 's_id': s_id, 'role': role, 'bid': bid},
            'access_token'
        )
        return new_access_token

    if db_rT is None:
        log_event(f"refresh_token истёк или подменён | s_id: {s_id}; user_id: {sub}", level="CRITICAL")
    # рефреш_токен ИСТЁК / НЕ СОВПАЛ / ОТОЗВАН
    return 401