"""
API для управления пользователями в ядре протокола (добавление/удаление)
"""
from fastapi import APIRouter, HTTPException
from starlette.requests import Request

from node_client.api.proto_core.hot_reload_executor import HotReloadExecutor
from node_client.api.proto_core.write_behind_caching_file import CoreBuffersDep
from node_client.schemas.proto_core_users_schema import AddUserCoreSchema, DeleteUserCoreSchema
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
    log_event(f"Добавление пользователя | node_proto_id: {body.node_proto_id} | uuid: {body.user_uuid}")
    
    hot_reload_success = False
    hot_reload_message = ""

    "1. Hot-reload через API (если есть библиотека)"
    if body.core_lib and body.add_script and body.core_port:
        try:
            log_event(f"Попытка hot-reload добавления через \033[33m{body.core_lib}\033[0m", request=request)
            
            hot_reload_success, hot_reload_message = await HotReloadExecutor.execute_add_script(
                script=body.add_script,
                lib_name=body.core_lib,
                user_obj=body.user_obj,
                node_ip='127.0.0.1',
                core_api_port=body.core_port,
            )
            
            if not hot_reload_success:
                log_event(f"Hot-reload FAILED: {hot_reload_message}. Продолжаем с файловой записью.", level='CRITICAL')

        except Exception as e:
            log_event(f"Исключение при hot-reload: {e}", request=request, level='CRITICAL')
            hot_reload_message = str(e)
    
    "2. Добавление в ConfigWriteBuffer"
    try:
        # Добавляем пользователя (метод сам разберётся с регистрацией ноды)
        await buffer.add_user(
            node_proto_id=body.node_proto_id,
            uuid=body.user_uuid,
            user_obj=body.user_obj,
            filepath=body.config_file_path,
            users_path=body.flatten_json_users_key,
            flatten_user_identifier_key=body.flatten_user_identifier_key,

            # обеспечивает авто sync при неудачных вставках пользователя через апи, т.к. каждый раз обновляет reload_command
            reload_command=body.reload_core_command if not hot_reload_success else None
        )
        
        log_event(f"Пользователь добавлен в буфер | uuid: {body.user_uuid}", request=request)

        return {
            'success': True, 'message': 'Пользователь добавлен', 'hot_reload': hot_reload_success, 'hot_reload_message': hot_reload_message
        }
        
    except Exception as e:
        log_event(f"Ошибка добавления пользователя: {e}", request=request, level='CRITICAL')
        raise HTTPException(status_code=500, detail=str(e))



@router.delete('/user/delete')
async def delete_user_from_core(body: DeleteUserCoreSchema, request: Request, buffer: CoreBuffersDep):
    """
    Удаление пользователя из ядра протокола
    
    Workflow:
    1. [Если есть core_lib] → Hot-reload через API (мгновенно)
    2. Удаление из буфера (O(1))
    3. Добавление в очередь на запись (батчинг)
    4. [Если нет hot-reload] → Перезагрузка ядра после записи файла
    """
    log_event(f"Удаление пользователя | node_proto_id: {body.node_proto_id} | uuid: {body.user_uuid}", request=request)
    
    hot_reload_success = False
    hot_reload_message = ""
    
    "1. Hot-reload через API (если есть библиотека)"
    if body.core_lib and body.delete_script and body.core_port:
        try:
            log_event(f"Попытка hot-reload удаления через {body.core_lib}", request=request)
            

            hot_reload_success, hot_reload_message = await HotReloadExecutor.execute_delete_script(
                script=body.delete_script,
                lib_name=body.core_lib,
                user_identifier=body.user_uuid,
                node_ip='127.0.0.1',
                core_api_port=body.core_port
            )
            
            if not hot_reload_success:
                log_event(f"Hot-reload DELETE FAILED: {hot_reload_message}. Продолжаем с файловой записью.", request=request, level='CRITICAL')
                
        except Exception as e:
            log_event(f"Исключение при hot-reload удаления: {e}", request=request, level='CRITICAL')
            hot_reload_message = str(e)
    
    "2. Удаление из ConfigWriteBuffer"
    await buffer.delete_user(body.node_proto_id, body.user_uuid)
    log_event(f"Пользователь удалён из буфера | uuid: {body.user_uuid}", request=request)
        
    return {
        'success': True, 'message': 'Пользователь удалён', 'hot_reload': hot_reload_success, 'hot_reload_message': hot_reload_message
    }
