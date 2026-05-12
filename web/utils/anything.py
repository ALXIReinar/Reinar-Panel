from dataclasses import dataclass

from starlette.requests import Request

from web.config_dir.config import env


@dataclass
class NodeUris:
    exec_cmd: str = '/api/v1/server/node/execute'
    get_config_file: str = '/api/v1/server/node/config/read'
    write_config_file: str = '/api/v1/server/node/config/write'
    ping: str = '/api/v1/server/node/ping'

@dataclass
class NodeStatus:
    """Статусы нод"""
    main: int = 1
    vpn_worker: int = 2
    balancer: int = 3

@dataclass
class TokenTypes:
    access_token: str = 'aT'
    refresh_token: str = 'rT'
    ws_token: str = 'wT'

token_types = {
    'access_token': 'aT',
    'refresh_token': 'rT',
    'ws_token': 'wT'
}


def get_client_ip(request: Request):
    xff = request.headers.get('X-Forwarded-For')
    ip = xff.split(',')[0].strip() if (
            xff and request.client.host in env.trusted_proxies
    ) else request.client.host
    return ip

def hide_log_param(param, start=3, end=8):
    return param[:start] + '*' * len(param[start:-end-1]) + param[-end:]