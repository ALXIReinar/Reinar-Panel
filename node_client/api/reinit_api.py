"""
Эндпоинт реинициализации виртуальных нод

Фактический маршрут: POST /api/v1/server/node/reinit
(от него зависит vnode-checker)
"""

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import JSONResponse

from node_client.api.proto_core.write_behind_caching_file import CoreBuffersDep
from node_client.config import AioHttpAdminDep
from node_client.exceptions import AdminPanelError, NodeInitError
from node_client.schemas.node_startup_schema import ReinitRequestSchema
from node_client.utils.logger_config import log_event

router = APIRouter(prefix='/node', tags=['Reinit'])


@router.post('/reinit', summary="Реинициализация виртуальных нод")
async def reinit_nodes(
    body: ReinitRequestSchema, buffer: CoreBuffersDep, admin_aiohttp: AioHttpAdminDep, request: Request
):
    """
    Реинициализация виртуальных нод без перезапуска нод-клиента (логика — ConfigWriteBuffer.reinit_nodes)

    - 502: админка недоступна или не знает ноду
    - 422: ошибка валидации/компиляции любой ноды, память нод-клиента не изменена
    """
    log_event(f"Запрос реинициализации | node_proto_ids: \033[34m{body.node_proto_ids}\033[0m", request=request)

    try:
        registered, removed = await buffer.reinit_nodes(admin_aiohttp, body.node_proto_ids)
    except AdminPanelError as e:
        log_event(
            f"Ошибка запроса /startup при реинициализации: \033[31m{repr(e)}\033[0m", request=request, level='ERROR'
        )
        return JSONResponse(
            status_code=502,
            content={"success": False, "message": f"Не удалось получить данные от админки: {str(e)}"},
        )
    except NodeInitError as e:
        log_event(
            f"Ошибка компиляции при реинициализации, память не изменена | node_proto_id: \033[31m{e.node_proto_id}\033[0m; field: \033[33m{e.field}\033[0m; reason: \033[34m{e.reason}\033[0m",
            request=request,
            level='ERROR',
        )
        return JSONResponse(
            status_code=422,
            content={"success": False, "node_proto_id": e.node_proto_id, "field": e.field, "reason": e.reason},
        )

    log_event(
        f"Реинициализация завершена | registered: \033[32m{registered}\033[0m; removed: \033[33m{removed}\033[0m",
        request=request,
    )
    return {'success': True, 'registered': registered, 'removed': removed}
