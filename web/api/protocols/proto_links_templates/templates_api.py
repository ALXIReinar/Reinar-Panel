from typing import Annotated

from fastapi import APIRouter, Query, HTTPException, Depends
from starlette.requests import Request

from web.data.postgres import PgSqlDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.templates_schema import AddTmpSchema, UpdateTmpSchema, GetTmpSchema
from web.utils.logger_config import log_event

router = APIRouter(tags=['Proto Templates'])



@router.get('/all')
async def get_all_templates(params: GetTmpSchema, request: Request, db: PgSqlDep, _: JWTCookieDep):
    """
    Получить список всех шаблонов конфиг-ссылок

    Фронт был бы весьма благодарен за структуру
    ```
    "spec_params": {
      tmp_id: [
          {"key": "pbk", "id": 1},
          {"key": "flow", "id": 2}
      ]
    }
    ```
    Текущая:
    ```
    "spec_params": [
      {
        "id": 1,
        "key": "pbk",
        "tmp_id": 1
      },
      {
        "id": 2,
        "key": "flow",
        "tmp_id": 1
      }
    ]
    ```
    """
    templates = await db.proto_templates.get_all(params.last_id, params.sort_by, params.limit)
    log_event(f'Отдали список шаблонов | tmp_len: \033[32m{len(templates["templates"])}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'success': True, **templates}


@router.get('/by_id')
async def get_tmp_by_id(
        tmp_id: Annotated[int, Query()], spec_only: Annotated[bool, Query(alias='so')], request: Request, db: PgSqlDep, _: JWTCookieDep
):
    """Получить шаблон по ID с привязанными spec параметрами"""
    result = await db.proto_templates.get_by_id(tmp_id, spec_only)
    
    if not result:
        log_event(f'Шаблон не найден | tmp_id: \033[31m{tmp_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request, level='WARNING')
        raise HTTPException(status_code=404, detail='Шаблон не найден')
    
    log_event(f'Отдали шаблон | tmp_id: \033[32m{tmp_id}\033[0m; spec_params_count: {len(result["spec_params"])}; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'success': True, 'template': result}


@router.post('/add')
async def add_template(body: AddTmpSchema, request: Request, db: PgSqlDep, _: JWTCookieDep):
    """Создать новый шаблон конфиг-ссылки"""
    log_event(f'Создание шаблона | title: \033[35m{body.title}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    status_code, message, template_id = await db.proto_templates.create(body.title)
    
    "Шаблон с таким именем уже существует"
    if status_code == 409:
        log_event(f'Конфликт при создании шаблона | title: \033[33m{body.title}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request, level='WARNING')
        raise HTTPException(status_code=409, detail={'success': False, 'message': message})
    
    log_event(f'Шаблон создан | tmp_id: \033[32m{template_id}\033[0m; admin_id: \033[32m{request.state.admin_id}\033[0m', request=request)
    return {'success': True, 'message': message, 'template_id': template_id}


@router.put('/update')
async def update_template(body: UpdateTmpSchema, request: Request, db: PgSqlDep, _: JWTCookieDep):
    log_event(f'Обновление шаблона | tmp_id: \033[35m{body.tmp_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    
    status_code, message = await db.proto_templates.update(
        tmp_id=body.tmp_id,
        title=body.title,
        url_tmp=body.url_tmp,
        reload_core_command=body.reload_core_command,
        required_user_data_obj=body.required_user_data_obj,
        constant_user_data_obj=body.constant_user_data_obj,
        api_add_user_script=body.api_add_user_script,
        api_delete_user_script=body.api_delete_user_script,
        proto_python_lib=body.proto_python_lib,
        flatten_json_users_key=body.flatten_json_users_key,
        flatten_user_identifier_key=body.flatten_user_identifier_key,
        sub_prepare_script=body.sub_prepare_script,
        sub_required_libs=body.sub_required_libs,
        api_bulk_delete_user_script=body.api_bulk_delete_user_script,
        api_bulk_add_user_script=body.api_bulk_add_user_script,
        metrics_parser_code=body.metrics_parser_code,
        metrics_command=body.metrics_command,
        add_script_custom_params=body.add_script_custom_params,
        delete_script_custom_params=body.delete_script_custom_params,
        bulk_delete_script_custom_params=body.bulk_delete_script_custom_params,
        bulk_add_script_custom_params=body.bulk_add_script_custom_params,
        api_metrics_script=body.api_metrics_script,
    )
    
    "Шаблон не найден"
    if status_code == 404:
        log_event(f'Шаблон не найден | tmp_id: \033[31m{body.tmp_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request, level='WARNING')
        raise HTTPException(status_code=404, detail={'success': False, 'message': message})

    log_event(f'Шаблон обновлён | tmp_id: \033[32m{body.tmp_id}\033[0m; body: \033[37m{repr(body)}\033[0m; admin_id: \033[32m{request.state.admin_id}\033[0m', request=request)
    return {'success': True, 'message': message}


@router.delete('/delete')
async def delete_template(tmp_id: Annotated[int, Query()], request: Request, db: PgSqlDep, _: JWTCookieDep):
    """Удалить шаблон конфиг-ссылки"""
    log_event(f'Удаление шаблона | tmp_id: \033[35m{tmp_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    
    status_code, message = await db.proto_templates.delete(tmp_id)
    
    "Этого шаблона не существует"
    if status_code == 404:
        log_event(f'Шаблон не найден | tmp_id: \033[31m{tmp_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request, level='WARNING')
        raise HTTPException(status_code=404, detail={'success': False, 'message': message})

    "Этот шаблон используется какими-то из протоколов"
    if status_code == 409:
        log_event(f'Невозможно удалить шаблон (используется) | tmp_id: \033[33m{tmp_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request, level='WARNING')
        raise HTTPException(status_code=409, detail={'success': False, 'message': message})

    log_event(f'Шаблон удалён | tmp_id: \033[32m{tmp_id}\033[0m; admin_id: \033[32m{request.state.admin_id}\033[0m', request=request, level='WARNING')
    return {'success': True, 'message': message}
