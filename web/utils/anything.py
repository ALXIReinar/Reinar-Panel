from dataclasses import dataclass
from ipaddress import IPv4Network, IPv6Network, ip_address

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
    proto_core_bulk_action: str = '/api/v1/server/proto_core/user/bulk/action'
    reinit: str = '/api/v1/server/node/reinit'


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
class VnodeRegStatuses:
    pending: int = 1
    success: int = 2
    failed: int = 3


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
    token_types = {'access_token': 'aT', 'refresh_token': 'rT', 'ws_token': 'wT'}
    excluded_commands_words = {
        'sudo',
    }
    proto_core_methods = {'add': NodeUris.proto_core_bulk_action, 'delete': NodeUris.proto_core_bulk_action}


def resolve_client_ip(peer: str | None, xff: str | None) -> str:
    """
    IP клиента по адресу TCP-соединения и заголовку X-Forwarded-For

    Заголовку верим только от доверенного прокси (TRUSTED_PROXIES): иначе его подставит кто угодно, кто достучится
    до порта админки напрямую. За прокси клиент — самый правый адрес цепочки, который сам не является прокси:
    левые адреса тоже приходят от клиента и могут быть поддельными.
    """
    if not peer:
        return 'unknown'
    if not xff or peer not in env.trusted_proxies:
        return peer
    chain = [ip.strip() for ip in xff.split(',') if ip.strip()]
    for ip in reversed(chain):
        if ip not in env.trusted_proxies:
            return ip
    # Вся цепочка из прокси (например, запрос от самой админки через caddy) — исходный адрес
    return chain[0] if chain else peer


def get_client_ip(request: Request) -> str:
    return resolve_client_ip(request.client.host if request.client else None, request.headers.get('X-Forwarded-For'))


def get_client_ip_by_scope(scope: Scope) -> str:
    # Имена заголовков в ASGI — в нижнем регистре
    xff = dict(scope.get('headers', [])).get(b'x-forwarded-for')
    client = scope.get('client')
    return resolve_client_ip(client[0] if client else None, xff.decode('latin-1') if xff else None)


def ip_in_networks(ip: str, networks: list[IPv4Network | IPv6Network]) -> bool:
    """Входит ли адрес в одну из сетей; не-IP (например, 'unknown') — нет"""
    try:
        address = ip_address(ip)
    except ValueError:
        return False
    return any(address in network for network in networks)


def hide_log_param(param, start=3, end=8):
    return param[:start] + '*' * len(param[start : -end - 1]) + param[-end:]
