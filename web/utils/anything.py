from dataclasses import dataclass

from starlette.requests import Request
from starlette.types import Scope

from web.config_dir.config import env


@dataclass
class NodeUris:
    exec_cmd: str = '/api/v1/server/node/execute'
    get_metrics: str = '/api/v1/server/node/metrics'
    get_config_file: str = '/api/v1/server/node/config/read'
    write_config_file: str = '/api/v1/server/node/config/write'
    ping: str = '/api/v1/server/node/ping'
    proto_core_add_user: str = '/api/v1/server/proto_core/user/add'
    proto_core_delete_user: str = '/api/v1/server/proto_core/user/delete'

class CoreProtoActions:
    add: int = 1
    delete: int = 2

    word_add: str = 'add'
    word_delete: str = 'delete'

    name2id: dict[str, int] = {
        'add': 1,
        'delete': 2,
    }
    id2name: dict[str, str] = {id: name for name, id in name2id.items()}

@dataclass
class NodeStatus:
    """Статусы нод"""
    main: int = 1
    vpn_worker: int = 2
    balancer: int = 3


@dataclass
class ExecHistoryStatuses:
    pending: int = 1
    success: int = 2
    failed_on_node: int = 3
    failed_on_admin: int = 4

@dataclass
class TokenTypes:
    access_token: str = 'aT'
    refresh_token: str = 'rT'
    ws_token: str = 'wT'




@dataclass
class Constants:
    token_types = {
        'access_token': 'aT',
        'refresh_token': 'rT',
        'ws_token': 'wT'
    }
    excluded_commands_words = {'sudo', }
    proto_core_methods = {
        'add': NodeUris.proto_core_add_user,
        'delete': NodeUris.proto_core_delete_user
    }


def get_client_ip(request: Request):
    xff = request.headers.get('X-Forwarded-For')
    ip = xff.split(',')[0].strip() if (
            xff and request.client.host in env.trusted_proxies
    ) else request.client.host
    return ip

def get_client_ip_by_scope(scope: Scope):
    # 1. Извлекаем все заголовки из scope
    headers = dict(scope.get("headers", []))

    # 2. Ищем x-forwarded-for (имена в ASGI всегда в нижнем регистре)
    xff = headers.get(b"x-forwarded-for")

    if xff:
        # 3. Декодируем байты и берем первый адрес (самый левый в списке)
        # XFF обычно имеет формат: "client, proxy1, proxy2"
        client_ip = xff.decode("utf-8").split(",")[0].strip()
    else:
        # 4. Фолбэк на стандартный scope["client"], если заголовка нет
        client = scope.get("client")
        client_ip = client[0] if client else "unknown"
    return client_ip


def hide_log_param(param, start=3, end=8):
    return param[:start] + '*' * len(param[start:-end-1]) + param[-end:]