from typing import Annotated  # noqa: I001

from aiohttp import ClientError
from fastapi import APIRouter, Path, Request, HTTPException
from fastapi.params import Query

from web.config_dir.config import NodeExecAiohttpDep
from web.data.postgres import PgSqlDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.node_schema import (
    NodeCreateSchema,
    NodeUpdateSchema,
    NodesGetSchema,
    GetNodeProtoSchema,
    NodeReinitSchema,
    StartupRequest,
    StartupResponse,
)
from web.api.nodes.handlers import push_reinit
from web.utils.anything import NodeUris
from web.utils.logger_config import log_event


router = APIRouter(prefix='/private/nodes', tags=['Physical Nodes (Servers)'])
server_router = APIRouter(prefix='/server/nodes', tags=['Physical Nodes (Servers)'])


@router.post('/create', summary="Создать физическую ноду")
async def bind_node_api(
    body: NodeCreateSchema, request: Request, db: PgSqlDep, _: JWTCookieDep, aio_http: NodeExecAiohttpDep
):
    log_event(
        f'Связываем админку с Нодой | ip: \033[32m{body.ip}\033[0m; private_ip: \033[33m{body.private_ip}\033[0m; api_port: \033[35m{body.api_port}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m',
        request=request,
    )
    # url = f'http://{body.private_ip}:{body.api_port}{NodeUris.ping}' if env.app_mode != AppMode.LOCAL else f'http://localhost:8100{NodeUris.ping}'
    url = f'http://{body.private_ip}:{body.api_port}{NodeUris.ping}'
    try:
        async with aio_http.get(url) as resp:
            resp = await resp.json()

    except ClientError as resp_err:
        "Нода не отвечает"
        log_event(
            f'Не удалось создать ноду. Ошибка при запросе | ip: \033[32m{body.ip}\033[0m; private_ip: \033[33m{body.private_ip}\033[0m; api_port: \033[35m{body.api_port}\033[0m',
            request=request,
            level='WARNING',
        )
        raise HTTPException(
            status_code=502,
            detail={'success': False, 'message': 'Не удалось связаться с нодой', 'err_message': str(repr(resp_err))},
        )

    "Обрабатываем ответ ноды"
    if not (resp.get('success') and resp.get('service')):
        log_event(
            f'Нода ответила, но не так, как ожидалось | ip: \033[32m{body.ip}\033[0m; private_ip: \033[33m{body.private_ip}\033[0m; api_port: \033[35m{body.api_port}\033[0m',
            request=request,
            level='WARNING',
        )
        raise HTTPException(
            status_code=400, detail={'success': False, 'message': 'Неизвестный ответ от ноды', 'node_resp': resp}
        )

    "Фиксируем имя в БД"
    node_id = await db.nodes.create_node(
        body.ip, body.private_ip, body.api_port, resp['service'], body.title, body.is_active
    )
    if not node_id:
        log_event(
            f'Сервер с таким приватным ip уже создан | ip: \033[32m{body.ip}\033[0m; private_ip: \033[33m{body.private_ip}\033[0m; api_port: \033[35m{body.api_port}\033[0m',
            request=request,
        )
        raise HTTPException(
            status_code=409,
            detail={
                'success': False,
                'message': 'Сервер с таким приватным/публичным ip уже создан. Создайте на нём виртуальную ноду',
            },
        )

    log_event(
        f'Успешно связались с нодой | node_name: \033[32m{resp["service"]}\033[0m; private_ip: \033[33m{body.private_ip}\033[0m; api_port: \033[35m{body.api_port}\033[0m; node_id: \033[33m{node_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m',
        request=request,
    )
    return {'success': True, 'node_id': node_id, 'node_name': resp['service'], 'message': 'Нода создана'}


@router.get('/all', summary="Получить все физические ноды")
async def get_all_nodes_api(
    q_params: Annotated[NodesGetSchema, Query()], db: PgSqlDep, request: Request, _: JWTCookieDep
):
    nodes = await db.nodes.get_all_nodes(q_params.is_active, q_params.limit, q_params.offset)
    log_event(
        f'Отдали все ноды | nodes_len: {len(nodes)}; is_active: \033[32m{q_params.is_active}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m',
        request=request,
    )
    return {'nodes': nodes}


@router.get('/{node_id}', summary="Получить физическую ноду")
async def get_node_api(node_id: int, request: Request, db: PgSqlDep, _: JWTCookieDep):
    node = await db.nodes.get_node(node_id)
    if not node:
        log_event(
            f"Нода не найдена | node_id: \033[34m{node_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m",
            request=request,
            level='WARNING',
        )
        raise HTTPException(status_code=404, detail={'success': False, 'message': 'Нода не найдена'})

    log_event(
        f'Отдали физическую ноду | node_id: \033[32m{node_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m',
        request=request,
    )
    return {'node': node}


@router.put('/update/{node_id}', summary="Обновить физическую ноду")
async def update_node_api(body: NodeUpdateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    status_code, res_msg = await db.nodes.update_node(
        body.node_id, body.ip, body.private_ip, body.api_port, body.title, body.is_active
    )
    if status_code == 409:
        log_event(
            f'Не удалось обновить ноду | node_id: \033[32m{body.node_id}\033[0m; err_message: {res_msg["err_message"]}; admin_id: \033[31m{request.state.admin_id}\033[0m',
            request=request,
            level='WARNING',
        )
        raise HTTPException(status_code=409, detail={'success': False, **res_msg})

    log_event(
        f"Обновлена нода | node_id: \033[33m{body.node_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m",
        request=request,
    )
    return {'success': True, 'message': 'Нода обновлена'}


@router.delete('/{node_id}', summary="Удалить физическую ноду")
async def delete_node_api(node_id: int, db: PgSqlDep, request: Request, _: JWTCookieDep):
    """КАСКАДНО удаляет все виртуальные ноды вместе с физической нодой"""
    await db.nodes.delete_node(node_id)
    log_event(
        f"Удалена нода | node_id: \033[31m{node_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m",
        request=request,
        level='WARNING',
    )
    return {'success': True, 'message': 'Нода удалена'}


@router.get('/{node_id}/vnodes', summary="Получить все протоколы на ноде")
async def get_node_protocols_api(
    node_id: int, q_params: Annotated[GetNodeProtoSchema, Query()], request: Request, db: PgSqlDep, _: JWTCookieDep
):
    protocols = await db.nodes.get_node_protocols(node_id, q_params.limit, q_params.offset)
    log_event(
        f'Отдали виртуальные ноды на физической протоколы ноды | node_id: \033[33m{node_id}\033[0m; count: \033[32m{len(protocols)}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m',
        request=request,
    )
    return {'protocols': protocols}


@router.post('/{node_id}/reinit', summary="Реинициализировать виртуальные ноды на нод-клиенте")
async def reinit_vnodes_api(
    node_id: Annotated[int, Path(ge=1, le=32_767)],  # nodes.id — smallint: больший ID дал бы 500 из asyncpg
    body: NodeReinitSchema,
    request: Request,
    db: PgSqlDep,
    aio_http: NodeExecAiohttpDep,
    _: JWTCookieDep,
):
    """
    Точечная реинициализация виртуальных нод физической ноды без перезапуска нод-клиента.

    Именно этот эндпоинт должен использовать фронт для интерфейса тонкой реинициализации виртуальных нод:
    после правки шаблона или параметров ноды нод-клиент заново берёт её данные из /startup и перекомпилирует скрипты.

    - node_proto_ids: виртуальные ноды этой физической ноды; пустой список — все её ноды
    - 200: {success, registered, removed} от нод-клиента; removed — ноды, которые админка больше не выдаёт
      (например, reg_status не success)
    - 400: в списке есть чужие или несуществующие виртуальные ноды (foreign_node_proto_ids)
    - 404: физической ноды нет; 409: у неё не задан приватный IP
    - 422: шаблон не прошёл проверку на нод-клиенте (node_proto_id, field, reason), память нод-клиента не изменена
    - 502: нод-клиент недоступен, отказал или сам не получил данные от админки
    """
    admin_id = request.state.admin_id
    log_event(
        f'Реинициализация виртуальных нод | node_id: \033[32m{node_id}\033[0m; node_proto_ids: \033[33m{body.node_proto_ids}\033[0m; admin_id: \033[31m{admin_id}\033[0m',
        request=request,
    )
    node = await db.nodes.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail={'success': False, 'message': 'Физическая нода не найдена'})
    if not node['private_ip']:
        raise HTTPException(
            status_code=409, detail={'success': False, 'message': 'У физической ноды не задан приватный IP'}
        )

    if body.node_proto_ids:
        foreign = await db.nodes.get_vnode_ids_not_on_node(node_id, body.node_proto_ids)
        if foreign:
            log_event(
                f'Реинициализация отклонена: виртуальные ноды не принадлежат физической ноде | node_id: \033[32m{node_id}\033[0m; foreign: \033[31m{foreign}\033[0m',
                request=request,
                level='WARNING',
            )
            raise HTTPException(
                status_code=400,
                detail={
                    'success': False,
                    'message': 'Виртуальные ноды не принадлежат этой физической ноде',
                    'foreign_node_proto_ids': foreign,
                },
            )

    try:
        status, node_resp = await push_reinit(aio_http, node['private_ip'], node['api_port'], body.node_proto_ids)
    except (ClientError, TimeoutError) as e:
        log_event(
            f'Нод-клиент недоступен для реинициализации | node_id: \033[32m{node_id}\033[0m; error: \033[31m{repr(e)}\033[0m',
            request=request,
            level='ERROR',
        )
        raise HTTPException(
            status_code=502,
            detail={'success': False, 'message': 'Нод-клиент недоступен', 'err_message': repr(e)},
        ) from e

    if status == 200:
        log_event(
            f'Нод-клиент реинициализировал виртуальные ноды | node_id: \033[32m{node_id}\033[0m; registered: \033[32m{node_resp.get("registered")}\033[0m; removed: \033[33m{node_resp.get("removed")}\033[0m',
            request=request,
        )
        return node_resp

    log_event(
        f'Нод-клиент не выполнил реинициализацию | node_id: \033[32m{node_id}\033[0m; status: \033[31m{status}\033[0m; response: \033[37m{node_resp}\033[0m',
        request=request,
        level='ERROR',
    )
    if status == 422:
        raise HTTPException(
            status_code=422,
            detail={
                'success': False,
                'message': 'Шаблон виртуальной ноды не прошёл проверку на нод-клиенте, память нод-клиента не изменена',
                'node_proto_id': node_resp.get('node_proto_id'),
                'field': node_resp.get('field'),
                'reason': node_resp.get('reason'),
            },
        )
    raise HTTPException(
        status_code=502,
        detail={
            'success': False,
            'message': 'Нод-клиент не выполнил реинициализацию',
            'node_client_status': status,
            'node_client_response': node_resp,
        },
    )


@server_router.post(
    '/{node_title}/startup',
    response_model=StartupResponse,
    summary="Выдача служебных данных виртуальных нод для нод-клиента",
)
async def get_node_startup_data(
    node_title: str,
    body: StartupRequest,
    db: PgSqlDep,
    request: Request,
):
    """
    Выдача служебных данных виртуальных нод физической ноды при инициализации нод-клиента.
    """
    startup_data = await db.nodes.get_startup_data(node_title, body.node_proto_ids)
    if startup_data is None:
        log_event(
            f'Физическая нода не найдена при запросе startup | node_title: \033[31m{node_title}\033[0m',
            request=request,
            level='WARNING',
        )
        raise HTTPException(
            status_code=404,
            detail={"success": False, "message": f"Физическая нода '{node_title}' не найдена"},
        )

    log_event(
        f'Выданы данные startup для нод-клиента | node_title: \033[32m{node_title}\033[0m; '
        f'vnodes_count: \033[33m{len(startup_data["nodes"])}\033[0m; missing: {startup_data["missing"]}',
        request=request,
    )
    return startup_data
