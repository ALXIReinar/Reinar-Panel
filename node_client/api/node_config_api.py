from pathlib import Path
import orjson
from fastapi import APIRouter
from starlette.responses import JSONResponse

from node_client.api.proto_core.write_behind_caching_file import flatten_key2value
from node_client.schemas.node_config_schema import ConfigReadSchema, ConfigReadResponseSchema, ConfigWriteSchema, \
    ConfigWriteResponseSchema

router = APIRouter(prefix='/node/config', tags=['Config'])




@router.post('/read', summary="Прочитать конфигурационный файл")
async def read_config(body: ConfigReadSchema):
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
            json_content = orjson.loads(content)
            flatten_key2value(json_content, body.flatten_json_users_key, delete_obj=True)
            content = orjson.dumps(json_content, option=orjson.OPT_INDENT_2).decode('utf-8')

        return ConfigReadResponseSchema(success=True, content=content, path=body.path)
    
    except PermissionError:
        return JSONResponse(status_code=403, content={"success": False, "message": "Нет прав для чтения файла", "path": body.path})
    
    except UnicodeDecodeError:
        return JSONResponse(status_code=400, content={"success": False, "message": "Файл не является текстовым или имеет неподдерживаемую кодировку", "path": body.path})
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": f"Ошибка чтения файла: {str(e)}", "path": body.path})


@router.post('/write', summary="Записать конфигурационный файл")
async def write_config(body: ConfigWriteSchema):
    """
    Записывает содержимое в конфигурационный файл на ноде.
    Создаёт файл если его нет, перезаписывает если существует.
    """
    try:
        file_path = Path(body.path)
        new_content = body.content

        "Если передан указатель, переносим пользователей из старого конфига в новый"
        if body.flatten_json_users_key:
            old_file_json = orjson.loads(body.content)
            new_file_json = orjson.loads(body.content)

            users_list = flatten_key2value(old_file_json, body.flatten_json_users_key)
            flatten_key2value(new_file_json, body.flatten_json_users_key, new_last_obj=users_list, replace_last_obj=True)

            new_content = orjson.dumps(new_file_json, option=orjson.OPT_INDENT_2).decode('utf-8')

        # Запись файла
        file_path.write_text(new_content, encoding='utf-8')
        
        return ConfigWriteResponseSchema(success=True, message="Файл успешно записан", path=body.path)
    
    except PermissionError:
        return JSONResponse(status_code=403, content={"success": False, "message": "Нет прав для записи файла", "path": body.path})
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": f"Ошибка записи файла: {str(e)}", "path": body.path})
