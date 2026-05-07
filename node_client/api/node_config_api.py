from pathlib import Path
from fastapi import APIRouter
from starlette.responses import JSONResponse

from node_client.schemas.node_config_schema import ConfigReadSchema, ConfigReadResponseSchema, ConfigWriteSchema, \
    ConfigWriteResponseSchema

router = APIRouter(prefix='/node/config', tags=['Config'])




@router.post('/read', summary="Прочитать конфигурационный файл")
async def read_config(body: ConfigReadSchema):
    """
    Читает содержимое конфигурационного файла на ноде.
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
        
        # Создаём директории если их нет
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Запись файла
        file_path.write_text(body.content, encoding='utf-8')
        
        return ConfigWriteResponseSchema(success=True, message="Файл успешно записан", path=body.path)
    
    except PermissionError:
        return JSONResponse(status_code=403, content={"success": False, "message": "Нет прав для записи файла", "path": body.path})
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": f"Ошибка записи файла: {str(e)}", "path": body.path})
