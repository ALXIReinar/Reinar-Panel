from fastapi import APIRouter
from starlette.requests import Request

from node_client.api.proto_core.hot_reload_executor import HotReloadExecutor
from node_client.api.proto_core.write_behind_caching_file import CoreBuffersDep
from node_client.config import CoreProtoActions
from node_client.schemas.proto_core_users_schema import BaseUserCoreSchema
from node_client.logger_config import log_event

router = APIRouter(prefix='/proto_core', tags=['Protocol Core Users'])



@router.put('/user/bulk/action')
async def bulk_action_users_core(body: BaseUserCoreSchema, request: Request, buffer: CoreBuffersDep):
    """
    Добавление пользователя в ядро протокола

    Workflow:
    1. [Если есть core_lib] → Hot-reload через API (мгновенно)
    2. Вставка в буфер (O(1))
    3. Добавление в очередь на запись (батчинг)
    4. [Если нет hot-reload] → Перезагрузка ядра после записи файла
    """
    log_event(f"Добавление пользователей | action: \033[33m{body.operation}\033[0m; node_proto_id: \033[32m{body.node_proto_id}\033[0m; users_len: \033[0m{len(body.users)}\033[0m", request=request)

    "0. Маппим действия в зависимости от операции"
    action_map = {
        CoreProtoActions.word_add: {'hre_action': 'bulk_add_users', "wbc_func": buffer.add_user},
        CoreProtoActions.word_delete: {'hre_action': 'bulk_delete_users', 'wbc_func': buffer.delete_user},
    }
    action_params = action_map[body.operation]
    hot_reload_success = False
    hot_reload_result = ""

    "1. Hot-reload через API (если есть скрипт)"
    if body.action_script and body.core_port:
        try:
            log_event(f"\033[32m[Bulk]]\033[0m Попытка hot-reload действия через {body.core_lib} | action: \033[33m{body.operation}\033[0m; node_proto_id: \033[32m{body.node_proto_id}\033[0m;", request=request)
            hot_reload_success, hot_reload_result = await HotReloadExecutor.execute_action_script(
                script=body.action_script,
                lib_names=body.core_lib,
                user_obj=body.users,
                node_ip='127.0.0.1',
                core_api_port=body.core_port,
                custom_params=body.custom_params,
                action=action_params['hre_action']
            )

            if not hot_reload_success:
                log_event(f"\033[32m[Bulk]\033[0m Hot-reload ADD FAILED: {hot_reload_result}. Продолжаем с файловой записью | action: \033[33m{body.operation}\033[0m; node_proto_id: \033[32m{body.node_proto_id}\033[0m;", request=request, level='ERROR')

        except Exception as e:
            log_event(f"\033[32m[Bulk]\033[0m Исключение при hot-reload вставки: {e}", request=request, level='CRITICAL')
            hot_reload_result = str(repr(e))


    "2. Действие из ConfigWriteBuffer без лимитов на операции"
    async with buffer.unlimit_queue(body.node_proto_id):
        for u in body.users:
            # Можно реализовать логику подсчёта успешных вставок по первому аргументу от add_user
            await action_params['wbc_func'](
                node_proto_id=body.node_proto_id,
                user_obj=u,
                filepath=body.config_file_path,
                user_injectors=[u_inj.model_dump() for u_inj in body.user_injectors],
                reload_command=body.reload_core_command,
            )

    log_event(f"\033[32m[Bulk]\033[0m Пользователей добавлено в буфер | action: \033[33m{body.operation}\033[0m; users_len: \033[31m{len(body.users)}\033[0m", request=request)

    return {
        'success': True, 'message': 'Пользователи добавлены', 'hot_reload': hot_reload_success, 'hot_reload_message': str(hot_reload_result)
    }
