import asyncio  # noqa: I001
from fastapi import APIRouter, HTTPException
from starlette.requests import Request

from node_client.api.proto_core.write_behind_caching_file import CoreBuffersDep
from node_client.schemas.proto_core_users_schema import BaseUserCoreSchema
from node_client.utils.logger_config import log_event

router = APIRouter(prefix='/proto_core', tags=['Protocol Core Users'])


@router.put('/user/bulk/action')
async def bulk_action_users_core(body: BaseUserCoreSchema, request: Request, buffer: CoreBuffersDep):
    """
    Добавление или удаление пользователей в ядро протокола

    Workflow:
    1. Получение метаданных виртуальной ноды из ConfigWriteBuffer
    2. [Если есть api_script] → Hot-reload через API (мгновенно)
    3. Вставка/удаление в буфер (O(1)) и добавление в очередь на запись (батчинг)
    """
    log_event(
        f"Операция над пользователями | action: \033[33m{body.action}\033[0m; node_proto_id: \033[32m{body.node_proto_id}\033[0m; users_len: \033[0m{len(body.users)}\033[0m",
        request=request,
    )

    meta = buffer.get_metadata(body.node_proto_id)

    hot_reload_success = False
    hot_reload_result = ""

    action_script = (
        meta.get('api_bulk_add_user_script') if body.action == 'add' else meta.get('api_bulk_delete_user_script')
    )

    if action_script and body.core_port:
        try:
            log_event(
                f"\033[32m[Bulk]\033[0m Попытка hot-reload действия | action: \033[33m{body.action}\033[0m; node_proto_id: \033[32m{body.node_proto_id}\033[0m;",
                request=request,
            )
            res = action_script(body.users, '127.0.0.1', body.core_port, body.custom_params or {})
            if asyncio.iscoroutine(res):
                res = await res
            hot_reload_success = True
            hot_reload_result = res
        except Exception as e:
            log_event(
                f"\033[32m[Bulk]\033[0m Ошибка при hot-reload: {e}",
                request=request,
                level='ERROR',
            )
            hot_reload_success = False
            hot_reload_result = str(repr(e))

    success, msg = await buffer.bulk_action(
        node_proto_id=body.node_proto_id,
        users=body.users,
        action=body.action,
    )

    level = "INFO" if success else "CRITICAL"
    log_event(
        f"\033[32m[Bulk]\033[0m Действие в буфере | action: \033[33m{body.action}\033[0m; users_len: \033[31m{len(body.users)}\033[0m; msg: \033[36m{msg}\033[0m",
        request=request,
        level=level,
    )
    if not success:
        raise HTTPException(status_code=500, detail={"success": False, "message": msg})

    return {
        'success': True,
        'message': 'Действие успешно выполнено',
        'hot_reload': hot_reload_success,
        'hot_reload_message': str(hot_reload_result),
    }
