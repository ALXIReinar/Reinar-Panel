from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import JSONResponse

from web.data.postgres import PgSqlDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.proto_schema import ProtocolCreateSchema, ProtoPagenSchema
from web.utils.logger_config import log_event

router = APIRouter(prefix='/protocols',tags=['Popular Protocols'])


@router.post('/create', summary="Создать протокол")
async def create_proto(body: ProtocolCreateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    proto_id = await db.protocols.create_protocol(body.name)
    if not proto_id:
        log_event(f'Такой протокол уже существует | name: \033[35m{body.name}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request, level='WARNING')
        return JSONResponse(status_code=409, content={"success": False, "message": f"Такой протокол '{body.name}' уже существует"})

    log_event(f"Создан протокол: \033[32m{body.name}\033[0m | proto_id: {proto_id}; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request)
    return {'success': True, 'proto_id': proto_id, 'message': 'Протокол создан'}


@router.get('/all', summary="Получить все протоколы")
async def get_all_protos(body: ProtoPagenSchema, db: PgSqlDep, _: JWTCookieDep):
    protocols = await db.protocols.get_all_protocols(body.offset, body.limit)
    if not protocols:
        log_event('Отдали все протоколы')

    return {'protocols': protocols}


@router.get('/{proto_id}', summary="Получить протокол")
async def get_proto(proto_id: int, db: PgSqlDep, request: Request, _: JWTCookieDep):
    protocol = await db.protocols.get_protocol(proto_id)
    if not protocol:
        log_event(f'Не нашли протокол | proto_id: \033[31m{proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Протокол не найден'})

    log_event(f'Отдали протокол | proto_id: \033[32m{proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'protocol': protocol}


@router.delete('/delete/{proto_id}', summary="Удалить протокол")
async def delete_proto(proto_id: int, db: PgSqlDep, request: Request, _: JWTCookieDep):
    deleted = await db.protocols.delete_protocol(proto_id)

    if deleted is None:
        log_event(f'Не удалось удалить протокол | proto_id: \033[33m{proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Протокол не найден'})

    log_event(f"Удалён протокол | proto_id: \033[31m{proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request, level='WARNING')
    return {'success': True, 'message': 'Протокол удалён'}
