import asyncio  # noqa: I001
from pathlib import Path
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
    # Вне try: NodeNotRegisteredError должна дойти до глобального обработчика (428), а не стать 500
    meta = buffer.get_metadata(body.node_proto_id)
    try:
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
    Переносит список пользователей из старого файла в новый — только если запрошено (transfer_users).
    Создаёт резервную копию перед записью.
    """
    # Вне try: NodeNotRegisteredError должна дойти до глобального обработчика (428), а не стать 500
    meta = buffer.get_metadata(body.node_proto_id)
    # Конвертеры — из метаданных, захваченных в начале: снятие ноды посреди записи не превращается в 500
    config_loader, config_dumper = meta['config2json_script'], meta['json2config_script']
    try:
        file_path = Path(body.path)
        new_file_json = config_loader(body.content)

        # Файловые операции — в отдельном потоке, чтобы не блокировать event loop нод-клиента
        file_existed = await asyncio.to_thread(file_path.exists)
        if file_existed and body.transfer_users:
            old_text = await asyncio.to_thread(file_path.read_text, encoding='utf-8')
            old_file_json = config_loader(old_text)
            for inj in meta.get('injectors', []):
                cursor = inj.get('flatten_array_cursor')
                if cursor:
                    users_list = flatten_key2value(old_file_json, cursor)
                    flatten_key2value(new_file_json, cursor, new_last_obj=users_list, replace_last_obj=True)

        _, config_link = generate_link_from_json(body.tmp_link, new_file_json)

        if file_existed:
            backup_path = await create_backup(str(file_path))
            if backup_path:
                log_event(
                    f"Создан бэкап конфига | node_proto_id: \033[33m{body.node_proto_id}\033[0m; backup: \033[32m{backup_path}\033[0m",
                    level='INFO',
                )

        new_content = config_dumper(new_file_json)
        if isinstance(new_content, str):
            new_content = new_content.encode('utf-8')
        await asyncio.to_thread(file_path.write_bytes, new_content)

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
