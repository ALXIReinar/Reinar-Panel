"""
Эндпоинт реинициализации виртуальных нод

Фактический маршрут: POST /api/v1/server/node/reinit
(от него зависит vnode-checker)
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from node_client.api.proto_core.write_behind_caching_file import CoreBuffersDep
from node_client.startup import fetch_startup_data
from node_client.utils.logger_config import log_event

router = APIRouter(prefix='/node', tags=['Reinit'])


class ReinitRequest(BaseModel):
    """Запрос на реинициализацию виртуальных нод"""

    node_proto_ids: list[int] = Field(default_factory=list, description="Пустой список = все зарегистрированные ноды")


class ReinitResponse(BaseModel):
    """Ответ реинициализации"""

    success: bool = True
    registered: list[int] = Field(default_factory=list)
    removed: list[int] = Field(default_factory=list)


@router.post('/reinit', summary="Реинициализация виртуальных нод")
async def reinit_nodes(body: ReinitRequest, buffer: CoreBuffersDep, request: Request):
    """
    Реинициализация виртуальных нод без перезапуска нод-клиента

    1. Запрашивает актуальные данные у админки через /startup
    2. Атомарно валидирует и компилирует все скрипты во временную структуру
    3. Подменяет метаданные в node_metadata
    4. Для нод из missing — удаляет метаданные, buffer_storage, local_state
    """
    from node_client.exceptions import NodeInitError

    log_event(
        f"Запрос реинициализации | node_proto_ids: \033[34m{body.node_proto_ids}\033[0m",
        request=request,
    )

    try:
        data = await fetch_startup_data(node_proto_ids=body.node_proto_ids)
    except RuntimeError as e:
        log_event(
            f"Ошибка запроса /startup при реинициализации: \033[31m{repr(e)}\033[0m",
            request=request,
            level='ERROR',
        )
        return JSONResponse(
            status_code=502,
            content={"success": False, "message": f"Не удалось получить данные от админки: {str(e)}"},
        )

    nodes = data.get('nodes', [])
    missing = data.get('missing', [])

    # Атомарная валидация: сначала компилируем все ноды во временную структуру
    # Если любая нода упадёт — откатываемся полностью
    temp_metadata: dict[int, dict] = {}

    for item in nodes:
        node_proto_id = item['node_proto_id']
        try:
            # Сохраняем текущие метаданные для отката
            await buffer.register_node(item)
            temp_metadata[node_proto_id] = buffer.node_metadata[node_proto_id]
        except NodeInitError as e:
            # Откат: восстанавливаем прежние метаданные для уже обработанных нод
            log_event(
                f"Ошибка компиляции при реинициализации | node_proto_id: \033[31m{e.node_proto_id}\033[0m; "
                f"field: \033[33m{e.field}\033[0m; reason: \033[34m{e.reason}\033[0m",
                request=request,
                level='ERROR',
            )
            return JSONResponse(
                status_code=422,
                content={
                    "success": False,
                    "node_proto_id": e.node_proto_id,
                    "field": e.field,
                    "reason": e.reason,
                },
            )

    # Удаляем ноды из missing (только явно запрошенные)
    removed_ids = []
    for node_proto_id in missing:
        if node_proto_id in buffer.node_metadata:
            del buffer.node_metadata[node_proto_id]
        if node_proto_id in buffer.buffer_storage:
            del buffer.buffer_storage[node_proto_id]
        if node_proto_id in buffer.local_state:
            del buffer.local_state[node_proto_id]
        removed_ids.append(node_proto_id)

    registered_ids = list(temp_metadata.keys())

    log_event(
        f"Реинициализация завершена | registered: \033[32m{registered_ids}\033[0m; "
        f"removed: \033[33m{removed_ids}\033[0m",
        request=request,
    )

    return ReinitResponse(
        success=True,
        registered=registered_ids,
        removed=removed_ids,
    )
