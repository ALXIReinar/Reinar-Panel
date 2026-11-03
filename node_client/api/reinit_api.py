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
from node_client.exceptions import NodeInitError
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

    1. Запрашивает актуальные данные у админки через /startup (одна попытка: вызывающий ждёт ответа)
    2. Проверяет и компилирует ВСЕ ноды во временную структуру. Ошибка любой ноды → 422,
       память нод-клиента не меняется (требования 4.5, 4.6)
    3. Применяет метаданные одним шагом; buffer_storage и local_state известных нод сохраняются
    4. Ноды из missing полностью убирает из памяти, включая воркер и очередь
    """
    log_event(
        f"Запрос реинициализации | node_proto_ids: \033[34m{body.node_proto_ids}\033[0m",
        request=request,
    )

    try:
        data = await fetch_startup_data(node_proto_ids=body.node_proto_ids, retries=1)
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

    "1. Проверка и компиляция во временную структуру. node_metadata пока не трогаем"
    compiled: dict[int, dict] = {}
    for item in data.get('nodes', []):
        try:
            compiled[item['node_proto_id']] = await buffer.compile_node(item)
        except NodeInitError as e:
            log_event(
                f"Ошибка компиляции при реинициализации, память не изменена | node_proto_id: \033[31m{e.node_proto_id}\033[0m; "
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

    "2. Все ноды валидны — применяем"
    await buffer.apply_nodes(compiled)

    "3. Ноды, которых админка больше не выдаёт (только из явно запрошенных)"
    removed_ids = []
    for node_proto_id in data.get('missing', []):
        await buffer.remove_node(node_proto_id)
        removed_ids.append(node_proto_id)

    registered_ids = list(compiled)
    log_event(
        f"Реинициализация завершена | registered: \033[32m{registered_ids}\033[0m; "
        f"removed: \033[33m{removed_ids}\033[0m",
        request=request,
    )
    return ReinitResponse(success=True, registered=registered_ids, removed=removed_ids)
