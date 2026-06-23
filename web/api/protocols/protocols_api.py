from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from starlette.requests import Request

from web.data.postgres import PgSqlDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.proto_schema import ProtocolCreateSchema, ProtoPagenSchema
from web.utils.logger_config import log_event

router = APIRouter(prefix='/protocols',tags=['Popular Protocols'])


@router.post('/create', summary="Создать протокол")
async def create_proto(body: ProtocolCreateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    status_code, msg, proto_id = await db.protocols.create_protocol(body.name, body.tmp_id)
    if status_code == 404:
        log_event(f'| name: \033[35m{body.name}\033[0m; tmp_id: \033[33m{body.tmp_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request, level='WARNING')
        raise HTTPException(status_code=404, detail={'success': False, 'message': msg})
    if not proto_id:
        log_event(f'Такой протокол уже существует | name: \033[35m{body.name}\033[0m; tmp_id: \033[33m{body.tmp_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request, level='WARNING')
        raise HTTPException(status_code=409, detail={"success": False, "message": f"Такой протокол '{body.name}' уже существует"})

    log_event(f"Создан протокол: \033[32m{body.name}\033[0m | proto_id: {proto_id}; tmp_id: \033[33m{body.tmp_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request)
    return {'success': True, 'proto_id': proto_id, 'message': msg}


@router.get('/all', summary="Получить все протоколы")
async def get_all_protos(q_params: Annotated[ProtoPagenSchema, Query()], request: Request, db: PgSqlDep, _: JWTCookieDep):
    protocols = await db.protocols.get_all_protocols(q_params.offset, q_params.limit, q_params.tmp_id)
    if not protocols:
        log_event(f'Отдали все протоколы | admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)

    log_event(f'Отдали протоколы | tmp_id для фильтра: \033[32m{q_params.tmp_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'protocols': protocols}


@router.get('/{proto_id}', summary="Получить протокол")
async def get_proto(proto_id: int, db: PgSqlDep, request: Request, _: JWTCookieDep):
    status_code, msg, proto_info = await db.protocols.get_protocol(proto_id)
    if status_code == 404:
        log_event(f'Не нашли протокол | proto_id: \033[31m{proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request, level='WARNING')
        raise HTTPException(status_code=404, detail={'success': False, 'message': msg})

    log_event(f'Отдали протокол | proto_id: \033[32m{proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'proto_info': proto_info}


@router.delete('/delete/{proto_id}', summary="Удалить протокол")
async def delete_proto(proto_id: int, db: PgSqlDep, request: Request, _: JWTCookieDep):
    status_code, msg = await db.protocols.delete_protocol(proto_id)

    if status_code == 409:
        log_event(f'Не удалось удалить протокол, Restrict Constraint | proto_id: \033[33m{proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
        raise HTTPException(status_code=409, detail={'success': False, "message": msg})

    log_event(f"Удалён протокол | proto_id: \033[31m{proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request, level='WARNING')
    return {'success': True, 'message': msg}
