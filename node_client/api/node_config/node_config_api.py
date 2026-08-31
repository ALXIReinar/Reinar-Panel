from pathlib import Path
import orjson
import time
import shutil
from starlette.requests import Request

from node_client.api.proto_core.write_behind_caching_file import CoreBuffersDep
from fastapi import APIRouter
from starlette.responses import JSONResponse

from node_client.api.proto_core.write_behind_caching_file import flatten_key2value
from node_client.api.sandbox.hot_reload_executor import HotReloadExecutor
from node_client.schemas.node_config_schema import ConfigReadSchema, ConfigReadResponseSchema, ConfigWriteSchema, \
    ConfigWriteResponseSchema
from node_client.utils.logger_config import log_event
from node_client.utils.tmp_url_render import generate_link_from_json
from node_client.config import TMP_DIR

router = APIRouter(prefix='/node/config', tags=['Config'])



@router.post('/read', summary="Прочитать конфигурационный файл")
async def read_config(body: ConfigReadSchema, buffer: CoreBuffersDep, request: Request):
    """
    Читает содержимое конфигурационного файла на ноде.
    Удаляет список пользователей из ответа (если указан flatten_json_users_key).
    """
    try:
        file_path = Path(body.path)
        
        "Проверка существования файла"
        if not file_path.exists():
            return JSONResponse(status_code=404, content={"success": False, "message": "Файл не найден", "path": body.path})
        
        "Проверка что это файл, а не директория"
        if not file_path.is_file():
            return JSONResponse(status_code=400, content={"success": False, "message": "Указанный путь не является файлом", "path": body.path})

        content = file_path.read_text(encoding='utf-8')

        "Если указатель на массив пользователей передан, отдаём конфиг без этого объекта пользователей"
        if body.flatten_json_users_key:

            "Пробуем достать конвертер-функции из работающей ноды(Кэш-пробинг)"
            if (node_meta := buffer.node_metadata.get(body.node_proto_id)) is not None:
                conf_loader = node_meta['config2json_script']
                conf_dumper = node_meta['json2config_script']
            else:
                if body.config2json_script is None:
                    conf_loader = lambda x: orjson.loads(x)
                else:
                    conf_loader = HotReloadExecutor.get_compiled_func(body.config2json_script, 'config2json', body.conf_converter_libs)
                
                if body.json2config_script is None:
                    conf_dumper = lambda x: orjson.dumps(x, option=orjson.OPT_INDENT_2)
                else:
                    conf_dumper = HotReloadExecutor.get_compiled_func(body.json2config_script, 'json2config', body.conf_converter_libs)

            "Удаляем указанные ключи, например список пользователей из dict(используем изменяемость объекта)"
            json_content = conf_loader(content)
            for flatten_cursor in body.flatten_json_users_key:
                flatten_key2value(json_content, flatten_cursor, delete_obj=True)
            content = conf_dumper(json_content).decode('utf-8') # json2config всегда отдаёт конфиг в байтах

        return ConfigReadResponseSchema(success=True, content=content, path=body.path)
    
    except PermissionError:
        log_event(f'Нет прав на чтение файла | node_proto_id: \033[33m{body.node_proto_id}\033[0m; file_path: \033[35m{body.path}\033[0m', request=request, level='WARNING')
        return JSONResponse(status_code=403, content={"success": False, "message": "Нет прав для чтения файла", "path": body.path})
    
    except UnicodeDecodeError:
        return JSONResponse(status_code=400, content={"success": False, "message": "Файл не является текстовым или имеет неподдерживаемую кодировку", "path": body.path})
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": f"Ошибка чтения файла: {str(e)}", "path": body.path})


@router.post('/write', summary="Записать конфигурационный файл")
async def write_config(body: ConfigWriteSchema, buffer: CoreBuffersDep):
    """
    Записывает содержимое в конфигурационный файл на ноде.
    Создаёт файл если его нет, перезаписывает если существует.
    """
    try:
        "Пробуем достать конвертер-функции из работающей ноды(Кэш-пробинг)"
        if (node_meta := buffer.node_metadata.get(body.node_proto_id)) is not None:
            conf_loader = node_meta['config2json_script']
            conf_dumper = node_meta['json2config_script']
        else:
            "Конвертер в json"
            if body.config2json_script is None:
                conf_loader = lambda x: orjson.loads(x)
            else:
                conf_loader = HotReloadExecutor.get_compiled_func(body.config2json_script, 'config2json', body.conf_converter_libs)

            "Обратно, в формат конфиг-файла"
            if body.json2config_script is None:
                conf_dumper = lambda x: orjson.dumps(x, option=orjson.OPT_INDENT_2)
            else:
                conf_dumper = HotReloadExecutor.get_compiled_func(body.json2config_script, 'json2config', body.conf_converter_libs)


        file_path = Path(body.path)
        new_file_json = conf_loader(body.content)

        "Если передан указатель, переносим пользователей из старого конфига в новый"
        if body.flatten_json_users_key:

            "Читаем старый файл"
            old_file_json = conf_loader(file_path.read_text(encoding='utf-8'))

            "Из старого забираем массив пользователей, прокидываем в новый файл"
            for flatten_cursor in body.flatten_json_users_key:
                users_list = flatten_key2value(old_file_json, flatten_cursor)
                flatten_key2value(new_file_json, flatten_cursor, new_last_obj=users_list, replace_last_obj=True)

        "Обновлённая конфиг-ссылка для впн-клиентов"
        _, config_link = generate_link_from_json(body.tmp_link, new_file_json)

        # Создаём резервную копию перед записью нового конфига
        if file_path.exists():
            backup_path = await create_backup(str(file_path))
            if backup_path:
                log_event(f"Создан бэкап конфига | node_proto_id: \033[33m{body.node_proto_id}\033[0m; backup: \033[32m{backup_path}\033[0m", level='INFO')

        "Запись файла"
        new_content = conf_dumper(new_file_json)
        file_path.write_bytes(new_content)

        return ConfigWriteResponseSchema(success=True, message="Файл успешно записан", path=body.path, config_link=config_link)
    
    except PermissionError:
        return JSONResponse(status_code=403, content={"success": False, "message": "Нет прав для записи файла", "path": body.path})
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": f"Ошибка записи файла: {str(e)}", "path": body.path})
