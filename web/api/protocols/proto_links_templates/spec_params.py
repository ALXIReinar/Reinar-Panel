from fastapi import APIRouter, HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from web.data.postgres import PgSqlDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.spec_params_schema import SpecParamsBulkAddSchema, SpecParamsBulkDeleteSchema
from web.utils.logger_config import log_event

router = APIRouter(tags=['Template Spec Params'])



@router.post('/bulk_add')
async def bulk_add_spec_params(body: SpecParamsBulkAddSchema, request: Request, db: PgSqlDep, _: JWTCookieDep):
    """Bulk добавление spec параметров к шаблону"""
    log_event(f'Bulk add spec параметров | tmp_id: \033[35m{body.tmp_id}\033[0m; keys_count: {len(body.keys)}; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    
    status_code, message, added_count = await db.template_spec_params.bulk_add(tmp_id=body.tmp_id, keys=body.keys)

    "Шаблон не найден"
    if status_code == 404:
        log_event( f'Шаблон не найден | tmp_id: \033[31m{body.tmp_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request, level='WARNING')
        raise HTTPException( status_code=404, detail={'success': False, 'message': message})

    log_event(f'Spec параметры добавлены | tmp_id: \033[32m{body.tmp_id}\033[0m; spec_len: {added_count}; admin_id: \033[32m{request.state.admin_id}\033[0m', request=request)
    return {'success': True, 'message': message, 'spec_len': added_count}


@router.delete('/bulk_delete')
async def bulk_delete_spec_params(body: SpecParamsBulkDeleteSchema, request: Request, db: PgSqlDep, _: JWTCookieDep):
    """Bulk удаление spec параметров"""
    log_event(f'Bulk delete spec параметров | count: {len(body.param_ids)}; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    
    status_code, message, deleted_count = await db.template_spec_params.bulk_delete(body.param_ids)

    "RESTRICT FK constraint"
    if status_code == 409:
        log_event('Невозможно удалить spec параметры. Их используют виртуальные ноды')
        raise HTTPException( status_code=409, detail={'success': False, 'message': message})

    log_event(f'Spec параметры удалены | deleted: \033[32m{deleted_count}\033[0m; admin_id: \033[32m{request.state.admin_id}\033[0m', request=request, level='WARNING')
    return {'success': True, 'message': message, 'deleted_count': deleted_count}
