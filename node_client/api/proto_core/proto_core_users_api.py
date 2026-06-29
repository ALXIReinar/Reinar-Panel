from fastapi import APIRouter, HTTPException
from starlette.requests import Request

from node_client.api.proto_core.hot_reload_executor import HotReloadExecutor
from node_client.api.proto_core.write_behind_caching_file import CoreBuffersDep
from node_client.schemas.proto_core_users_schema import AddUserCoreSchema, DeleteUserCoreSchema, \
    BulkDeleteUserCoreSchema, BulkAddUserCoreSchema
from node_client.logger_config import log_event

router = APIRouter(prefix='/proto_core', tags=['Protocol Core Users'])


@router.post('/user/add')
async def add_user_to_core(body: AddUserCoreSchema, request: Request, buffer: CoreBuffersDep):
    """
    Добавление пользователя в ядро протокола
    
    Workflow:
    1. [Если есть core_lib] → Hot-reload через API (мгновенно)
    2. Добавление в буфер (O(1))
       - Если нода не зарегистрирована → регистрируем автоматически
       - Если пользователь уже в буфере → обновляем
    3. Добавление в очередь на запись (батчинг)
    4. [Если нет hot-reload] → Перезагрузка ядра после записи файла
    """
    log_event(f"Добавление пользователя | node_proto_id: \033[35m{body.node_proto_id}\033[0m | user_obj: \033[34m{body.user_obj}\033[0m")

    hot_reload_success = False
    hot_reload_message = ""

    "1. Hot-reload через API (если есть скрипт)"
    if body.add_script and body.core_port:
        try:
            log_event(f"Попытка hot-reload добавления через \033[33m{body.core_lib}\033[0m", request=request)

            hot_reload_success, hot_reload_message = await HotReloadExecutor.execute_action_script(
                script=body.add_script,
                lib_names=body.core_lib,
                user_obj=body.user_obj,
                node_ip='127.0.0.1',
                core_api_port=body.core_port,
                custom_params=body.custom_params,
                action='add_user',
            )

            if not hot_reload_success:
                log_event(f"Hot-reload FAILED: \033[31m{hot_reload_message}\033[0m. Продолжаем с файловой записью.", level='CRITICAL')

        except Exception as e:
            log_event(f"Исключение при hot-reload: \033[34m{e}\033[0m", request=request, level='CRITICAL')
            hot_reload_message = str(e)

    "2. Добавление в ConfigWriteBuffer"
    # Добавляем пользователя (метод сам разберётся с регистрацией ноды)
    add_res, status_code, msg = await buffer.add_user(
        node_proto_id=body.node_proto_id,
        user_obj_or_identifier=body.user_obj,
        filepath=body.config_file_path,
        users_path=body.flatten_json_users_key,
        flatten_user_identifier_key=body.flatten_user_identifier_key,

        # Обеспечивает авто sync при неудачных вставках пользователя через апи, т.к. каждый раз обновляет reload_command
        reload_command=body.reload_core_command if not hot_reload_success else None
    )

    # buffer.add_user при успехе отдаёт сообщение, мол, всё хорошо
    if add_res:
        log_event(f"Пользователь добавлен в буфер | user_obj: \033[37m{body.user_obj}\033[0m", request=request)
        return {'success': True, 'message': msg, 'hot_reload': hot_reload_success, 'hot_reload_message': hot_reload_message}

    # При ошибке, отдаёт в сообщении ошибку из core_buffer - Поэтому стоят неочевидно
    log_event(f'Не удалось добавить пользователя в буфер, некорректные настройки | user_obj: \033[31m{body.user_obj}\033[0m', request=request, level='CRITICAL')
    raise HTTPException(status_code=status_code, detail={'success': False, 'message': 'Ошибка добавления пользователя в ядро', 'error_message': msg})




@router.post('/user/delete', summary='POST выбран ввиду нюансов реализации сервиса подписок. Не рекомендуется менять')
async def delete_user_from_core(body: DeleteUserCoreSchema, request: Request, buffer: CoreBuffersDep):
    """
    Удаление пользователя из ядра протокола
    
    Workflow:
    1. [Если есть core_lib] → Hot-reload через API (мгновенно)
    2. Удаление из буфера (O(1))
    3. Добавление в очередь на запись (батчинг)
    4. [Если нет hot-reload] → Перезагрузка ядра после записи файла
    """
    log_event(f"Удаление пользователя | node_proto_id: {body.node_proto_id} | uuid: \033[33m{body.user_obj}\033[0m", request=request)
    
    hot_reload_success = False
    hot_reload_message = ""
    
    "1. Hot-reload через API (если есть скрипт)"
    if body.delete_script and body.core_port:
        try:
            log_event(f"Попытка hot-reload удаления через {body.core_lib}", request=request)
            

            hot_reload_success, hot_reload_message = await HotReloadExecutor.execute_action_script(
                script=body.delete_script,
                lib_names=body.core_lib,
                user_obj=body.user_obj,
                node_ip='127.0.0.1',
                core_api_port=body.core_port,
                custom_params=body.custom_params,
                action='delete_user'
            )
            
            if not hot_reload_success:
                log_event(f"Hot-reload DELETE FAILED: {hot_reload_message}. Продолжаем с файловой записью.", request=request, level='CRITICAL')
                
        except Exception as e:
            log_event(f"Исключение при hot-reload удаления: {e}", request=request, level='CRITICAL')
            hot_reload_message = str(e)
    
    "2. Удаление из ConfigWriteBuffer"
    del_res, status_code, msg = await buffer.delete_user(
        node_proto_id=body.node_proto_id,
        user_obj_or_identifier=body.user_obj,
        filepath=body.config_file_path,
        users_path=body.flatten_json_users_key,
        flatten_user_identifier_key=body.flatten_user_identifier_key,
        reload_command=body.reload_core_command
    )


    # buffer.delete_user при успехе отдаёт сообщение, мол, всё хорошо
    if del_res:
        log_event(f"Пользователь удалён из буфера | user_obj: \033[37m{body.user_obj}\033[0m", request=request)
        return {'success': True, 'message': msg, 'hot_reload': hot_reload_success, 'hot_reload_message': hot_reload_message}

    # При ошибке, отдаёт в сообщении ошибку из core_buffer - Поэтому стоят неочевидно
    log_event(f'Не удалось удалить пользователя из буфера | user_obj: \033[31m{body.user_obj}\033[0m', request=request, level='WARNING')
    raise HTTPException(status_code=status_code, detail={'success': False, 'message': 'Ошибка удаления пользователя из ядра', 'error_message': msg})



@router.delete('/user/bulk/delete')
async def bulk_delete_user_from_core(body: BulkDeleteUserCoreSchema, request: Request, buffer: CoreBuffersDep):
    """
    Удаление пользователя из ядра протокола

    Workflow:
    1. [Если есть core_lib] → Hot-reload через API (мгновенно)
    2. Удаление из буфера (O(1))
    3. Добавление в очередь на запись (батчинг)
    4. [Если нет hot-reload] → Перезагрузка ядра после записи файла

    * Но
    """
    log_event(f"Удаление пользователей | node_proto_id: {body.node_proto_id} | users_len: \033[0m{len(body.users)}\033[0m", request=request)

    hot_reload_success = False
    hot_reload_message = ""
    "1. Hot-reload через API (если есть скрипт)"
    if body.bulk_delete_script and body.core_port:
        try:
            log_event(f"\033[33m[Bulk Delete]\033[0m Попытка hot-reload удаления через {body.core_lib}", request=request)

            hot_reload_success, hot_reload_message = await HotReloadExecutor.execute_action_script(
                script=body.bulk_delete_script,
                lib_names=body.core_lib,
                user_obj=body.model_dump()['users'],
                node_ip='127.0.0.1',
                core_api_port=body.core_port,
                custom_params=body.custom_params,
                action='bulk_delete_users'
            )

            if not hot_reload_success:
                log_event(f"\033[33m[Bulk Delete]\033[0m Hot-reload DELETE FAILED: {hot_reload_message}. Продолжаем с файловой записью.", request=request, level='ERROR')

        except Exception as e:
            log_event(f"\033[33m[Bulk Delete]\033[0m Исключение при hot-reload удаления: {e}", request=request, level='CRITICAL')
            hot_reload_message = str(e)

    "2. Удаление из ConfigWriteBuffer без лимитов на операции"
    async with buffer.unlimit_queue(body.node_proto_id):
        for u in body.users:
            # Можно реализовать логику подсчёта успешных удалений по первому аргументу от delete_user
            await buffer.delete_user(
                node_proto_id=body.node_proto_id,
                user_obj_or_identifier=u.uuid,
                filepath=body.config_file_path,
                users_path=body.flatten_json_users_key,
                flatten_user_identifier_key=body.flatten_user_identifier_key,
                reload_command=body.reload_core_command,
            )

    log_event(f"\033[33m[Bulk Delete]\033[0m Пользователей удалено из буфера | users_len: \033[31m{len(body.users)}\033[0m", request=request)

    return {
        'success': True, 'message': 'Пользователи удалены', 'hot_reload': hot_reload_success, 'hot_reload_message': hot_reload_message
    }



@router.post('/user/bulk/add')
async def bulk_add_user_into_core(body: BulkAddUserCoreSchema, request: Request, buffer: CoreBuffersDep):
    """
    Добавление пользователя в ядро протокола

    Workflow:
    1. [Если есть core_lib] → Hot-reload через API (мгновенно)
    2. Вставка в буфер (O(1))
    3. Добавление в очередь на запись (батчинг)
    4. [Если нет hot-reload] → Перезагрузка ядра после записи файла
    """
    log_event(f"Добавление пользователей | node_proto_id: {body.node_proto_id} | users_len: \033[0m{len(body.users)}\033[0m", request=request)

    hot_reload_success = False
    hot_reload_message = ""
    "1. Hot-reload через API (если есть скрипт)"
    if body.bulk_add_script and body.core_port:
        try:
            log_event(f"\033[32m[Bulk Add\033[0m Попытка hot-reload добавления через {body.core_lib}", request=request)

            hot_reload_success, hot_reload_message = await HotReloadExecutor.execute_action_script(
                script=body.bulk_add_script,
                lib_names=body.core_lib,
                user_obj=body.model_dump()['users'],
                node_ip='127.0.0.1',
                core_api_port=body.core_port,
                custom_params=body.custom_params,
                action='bulk_add_users'
            )

            if not hot_reload_success:
                log_event(f"\033[32m[Bulk Add\033[0m Hot-reload ADD FAILED: {hot_reload_message}. Продолжаем с файловой записью.", request=request, level='ERROR')

        except Exception as e:
            log_event(f"\033[32m[Bulk Add\033[0m Исключение при hot-reload вставки: {e}", request=request, level='CRITICAL')
            hot_reload_message = str(e)

    "2. Вставка из ConfigWriteBuffer без лимитов на операции"
    async with buffer.unlimit_queue(body.node_proto_id):
        for u in body.users:
            # Можно реализовать логику подсчёта успешных вставок по первому аргументу от add_user
            await buffer.add_user(
                node_proto_id=body.node_proto_id,
                user_obj_or_identifier=u,
                filepath=body.config_file_path,
                users_path=body.flatten_json_users_key,
                flatten_user_identifier_key=body.flatten_user_identifier_key,
                reload_command=body.reload_core_command,
            )

    log_event(f"\033[32m[Bulk Add]\033[0m Пользователей добавлено в буфер | users_len: \033[31m{len(body.users)}\033[0m", request=request)

    return {
        'success': True, 'message': 'Пользователи добавлены', 'hot_reload': hot_reload_success, 'hot_reload_message': hot_reload_message
    }
