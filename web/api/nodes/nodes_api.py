from typing import Annotated

from aiohttp import ClientError
from fastapi import APIRouter, Request, HTTPException
from fastapi.params import Query
from starlette.responses import JSONResponse

from web.config_dir.config import NodeExecAiohttpDep, env
from web.config_dir.env_modes import AppMode
from web.data.postgres import PgSqlDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.node_schema import NodeCreateSchema, NodeUpdateSchema, NodesGetSchema
from web.utils.anything import NodeUris
from web.utils.logger_config import log_event


router = APIRouter(tags=['Physical Nodes (Servers)'])



@router.post('/create', summary="Создать физическую ноду")
async def bind_node_api(body: NodeCreateSchema, request: Request, db: PgSqlDep, _: JWTCookieDep, aio_http: NodeExecAiohttpDep):
    log_event(f'Связываем админку с Нодой | ip: \033[32m{body.ip}\033[0m; private_ip: \033[33m{body.private_ip}\033[0m; api_port: \033[35m{body.api_port}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    # url = f'http://{body.private_ip}:{body.api_port}{NodeUris.ping}' if env.app_mode != AppMode.LOCAL else f'http://localhost:8100{NodeUris.ping}'
    url = f'http://{body.private_ip}:{body.api_port}{NodeUris.ping}'
    try:
        async with aio_http.get(url) as resp:
            resp = await resp.json()

    except ClientError as resp_err:
        "Нода не отвечает"
        log_event(f'Не удалось создать ноду. Ошибка при запросе | ip: \033[32m{body.ip}\033[0m; private_ip: \033[33m{body.private_ip}\033[0m; api_port: \033[35m{body.api_port}\033[0m', request=request, level='WARNING')
        raise HTTPException(status_code=502, detail={'success': False, 'message': 'Не удалось связаться с нодой','err_message': str(repr(resp_err))})

    "Обрабатываем ответ ноды"
    if not (resp.get('success') and resp.get('service')):
        log_event(f'Нода ответила, но не так, как ожидалось | ip: \033[32m{body.ip}\033[0m; private_ip: \033[33m{body.private_ip}\033[0m; api_port: \033[35m{body.api_port}\033[0m', request=request, level='WARNING')
        raise HTTPException(status_code=400, detail={'success': False, 'message': 'Неизвестный ответ от ноды', 'node_resp': resp})

    "Фиксируем имя в БД"
    node_id = await db.nodes.create_node(
        body.ip, body.private_ip, body.api_port, resp['service'], body.title, body.is_active
    )
    if not node_id:
        log_event(f'Сервер с таким приватным ip уже создан | ip: \033[32m{body.ip}\033[0m; private_ip: \033[33m{body.private_ip}\033[0m; api_port: \033[35m{body.api_port}\033[0m', request=request)
        raise HTTPException(status_code=409, detail={'success': False, 'message': 'Сервер с таким приватным/публичным ip уже создан. Создайте на нём виртуальную ноду'})

    log_event(f'Успешно связались с нодой | node_name: \033[32m{resp['service']}\033[0m; private_ip: \033[33m{body.private_ip}\033[0m; api_port: \033[35m{body.api_port}\033[0m; node_id: \033[33m{node_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'success': True, 'node_id': node_id, 'node_name': resp['service'], 'message': 'Нода создана'}


@router.get('/all', summary="Получить все физические ноды")
async def get_all_nodes_api(q_params: Annotated[NodesGetSchema, Query()], db: PgSqlDep, request: Request, _: JWTCookieDep):
    nodes = await db.nodes.get_all_nodes(q_params.is_active, q_params.limit, q_params.offset)
    log_event(f'Отдали все ноды | nodes_len: {len(nodes)}; is_active: \033[32m{q_params.is_active}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'nodes': nodes}


@router.get('/{node_id}', summary="Получить физическую ноду")
async def get_node_api(node_id: int, request: Request, db: PgSqlDep, _: JWTCookieDep):
    node = await db.nodes.get_node(node_id)
    if not node:
        log_event(f"Нода не найдена | node_id: \033[34m{node_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request, level='WARNING')
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Нода не найдена'})

    log_event(f'Отдали физическую ноду | node_id: \033[32m{node_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'node': node}


@router.put('/update/{node_id}', summary="Обновить физическую ноду")
async def update_node_api(body: NodeUpdateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    status_code, res_msg = await db.nodes.update_node(body.node_id, body.ip, body.private_ip, body.api_port, body.title, body.is_active)
    if status_code == 409:
        log_event(f'Не удалось обновить ноду | node_id: \033[32m{body.node_id}\033[0m; err_message: {res_msg['err_message']}; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request, level='WARNING')
        raise HTTPException(status_code=409, detail={'success': False, **res_msg})

    log_event(f"Обновлена нода | node_id: \033[33m{body.node_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request)
    return {'success': True, 'message': 'Нода обновлена'}


@router.delete('/{node_id}', summary="Удалить физическую ноду")
async def delete_node_api(node_id: int, db: PgSqlDep, request: Request, _: JWTCookieDep):
    """КАСКАДНО удаляет все виртуальные ноды вместе с физической нодой"""
    await db.nodes.delete_node(node_id)
    log_event(f"Удалена нода | node_id: \033[31m{node_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request, level='WARNING')
    return {'success': True, 'message': 'Нода удалена'}


