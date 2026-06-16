from typing import Annotated

from fastapi import APIRouter
from fastapi.params import Query
from starlette.requests import Request

from web.data.postgres import PgSqlDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.spec_params_schema import SpecValuesSetSchema, SpecKeysSetSchema, GetSpecValuesSchema
from web.utils.logger_config import log_event

router = APIRouter(prefix='/specs',tags=['Template Spec Params'])


@router.get('/vnode/get_spec_values')
async def get_spec_values_api(q_params: Annotated[GetSpecValuesSchema, Query()], request: Request, db: PgSqlDep, _: JWTCookieDep):
    spec_values = await db.template_spec_params.get_vnode_spec_params(q_params.node_proto_id)

    log_event(f'Отобразили значения по ключам для шаблонной конфиг-ссылки | node_proto_id: \033[32m{q_params.node_proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'spec_params': spec_values}

@router.put('/set_keys')
async def set_spec_keys_api(body: SpecKeysSetSchema, request: Request, db: PgSqlDep, _: JWTCookieDep):
    """
    Синхронизация spec параметров виртуальной ноды (UPSERT)
    """
    log_event(f'Задаём Spec ключи | tmp_id: \033[35m{body.tmp_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)

    res = await db.template_spec_params.set_spec_keys(
        tmp_id=body.tmp_id,
        del_keys=body.del_keys,
        upd_keys=[obj.model_dump() for obj in body.update_keys],
        add_keys=[obj.model_dump() for obj in body.add_keys],
    )
    log_event(f'Spec ключи заданы | tmp_id: \033[32m{body.tmp_id}\033[0m; admin_id: \033[32m{request.state.admin_id}\033[0m', request=request)
    return res


@router.put('/vnode/set_key_values')
async def set_spec_params_values(body: SpecValuesSetSchema, request: Request, db: PgSqlDep, _: JWTCookieDep):
    """Синхронизация spec параметров виртуальной ноды (UPSERT)"""
    log_event(f'Set spec значений | node_proto_id: \033[33m{body.node_proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)

    await db.template_spec_params.set_spec_values(
        node_proto_id=body.node_proto_id, new_specs=[obj.model_dump() for obj in body.spec_param_values]
    )

    log_event(f'spec_values синхронизированы | \033[33m{body.node_proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'success': True, 'message': "Specs успешно заданы"}
