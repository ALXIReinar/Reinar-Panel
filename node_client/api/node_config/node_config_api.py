from pathlib import Path  # noqa: I001
from starlette.requests import Request
from fastapi import APIRouter
from starlette.responses import JSONResponse

from node_client.api.proto_core.write_behind_caching_file import (
    CoreBuffersDep,
    flatten_key2value,
)
from node_client.api.node_config.handlers import create_backup
from node_client.schemas.node_config_schema import (
    ConfigReadSchema,
    ConfigReadResponseSchema,
    ConfigWriteSchema,
    ConfigWriteResponseSchema,
)
from node_client.utils.logger_config import log_event
from node_client.utils.tmp_url_render import generate_link_from_json

router = APIRouter(prefix='/node/config', tags=['Config'])


@router.post('/read', summary="Прочитать конфигурационный файл")
async def read_config(body: ConfigReadSchema, buffer: CoreBuffersDep, request: Request):
    """
    Читает содержимое конфигурационного файла на ноде.
    Удаляет список пользователей из ответа (если exclude_users=True, по умолчанию True).
    """
    try:
        meta = buffer.get_metadata(body.node_proto_id)
        file_path = Path(body.path)

        if not file_path.exists():
            return JSONResponse(
                status_code=404,
                content={"success": False, "message": "Файл не найден", "path": body.path},
            )
        if not file_path.is_file():
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Указанный путь не является файлом", "path": body.path},
            )

        content = file_path.read_text(encoding='utf-8')

        if body.exclude_users:
            json_content = buffer.read_config_json(body.node_proto_id, content)
            for inj in meta.get('injectors', []):
                cursor = inj.get('flatten_array_cursor')
                if cursor:
                    flatten_key2value(json_content, cursor, delete_obj=True)
            content = buffer.dump_config(body.node_proto_id, json_content).decode('utf-8')

        return ConfigReadResponseSchema(success=True, content=content, path=body.path)
    except PermissionError:
        log_event(
            f'Нет прав на чтение файла | node_proto_id: \033[33m{body.node_proto_id}\033[0m; file_path: \033[35m{body.path}\033[0m',
            request=request,
            level='WARNING',
        )
        return JSONResponse(
            status_code=403,
            content={"success": False, "message": "Нет прав для чтения файла", "path": body.path},
        )
    except UnicodeDecodeError:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "message": "Файл не является текстовым или имеет неподдерживаемую кодировку",
                "path": body.path,
            },
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"Ошибка чтения файла: {str(e)}", "path": body.path},
        )


@router.post('/write', summary="Записать конфигурационный файл")
async def write_config(body: ConfigWriteSchema, buffer: CoreBuffersDep, request: Request):
    """
    Записывает содержимое в конфигурационный файл на ноде.
    Переносит список пользователей из старого файла в новый.
    Создаёт резервную копию перед записью.
    """
    try:
        meta = buffer.get_metadata(body.node_proto_id)
        file_path = Path(body.path)
        new_file_json = buffer.read_config_json(body.node_proto_id, body.content)

        if file_path.exists():
            old_file_json = buffer.read_config_json(body.node_proto_id, file_path.read_text(encoding='utf-8'))
            for inj in meta.get('injectors', []):
                cursor = inj.get('flatten_array_cursor')
                if cursor:
                    users_list = flatten_key2value(old_file_json, cursor)
                    flatten_key2value(new_file_json, cursor, new_last_obj=users_list, replace_last_obj=True)

        _, config_link = generate_link_from_json(body.tmp_link, new_file_json)

        if file_path.exists():
            backup_path = await create_backup(str(file_path))
            if backup_path:
                log_event(
                    f"Создан бэкап конфига | node_proto_id: \033[33m{body.node_proto_id}\033[0m; backup: \033[32m{backup_path}\033[0m",
                    level='INFO',
                )

        new_content = buffer.dump_config(body.node_proto_id, new_file_json)
        file_path.write_bytes(new_content)

        return ConfigWriteResponseSchema(
            success=True,
            message="Файл успешно записан",
            path=body.path,
            config_link=config_link,
        )
    except PermissionError:
        return JSONResponse(
            status_code=403,
            content={"success": False, "message": "Нет прав для записи файла", "path": body.path},
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"Ошибка записи файла: {str(e)}", "path": body.path},
        )
