from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass
class TgBotApi:
    send_message: str = 'https://api.telegram.org/bot{}/sendMessage'


@dataclass
class DeleteReasons:
    sub_revoke: str = 'sub_revoke'
    admin_bulk_delete: str = 'admin_bulk_delete'


@dataclass
class AddReasons: ...


class CoreProtoActions:
    reason_del: DeleteReasons = DeleteReasons
    reason_add: AddReasons = AddReasons

    add: int = 1
    delete: int = 2

    word_add: str = 'add'
    word_delete: str = 'delete'

    name2id: dict[str, int] = {
        'add': 1,
        'delete': 2,
    }
    id2name: dict[str, str] = {id: name for name, id in name2id.items()}

    # Поле шаблона (proto_templates) с custom_params скрипта для каждой операции
    custom_params_field: dict[int, str] = {
        1: 'bulk_add_script_custom_params',
        2: 'bulk_delete_script_custom_params',
    }

    @classmethod
    def custom_params(cls, vnode: Mapping[str, Any], operation: int) -> dict | None:
        """custom_params скрипта шаблона для операции add(1)/delete(2); слово действия — через name2id"""
        return vnode[cls.custom_params_field[operation]]


@dataclass
class VnodeRegStatuses:
    pending: int = 1
    success: int = 2
    failed: int = 3


@dataclass
class UserStatuses:
    not_connect: int = 1
    offline: int = 2
    online: int = 3


@dataclass
class NodeUris:
    proto_core_bulk_action: str = (
        '/api/v1/server/proto_core/user/bulk/action'  # Experimental. Ещё не добавлено  на нод клиент
    )

    get_metrics: str = '/api/v1/server/node/metrics'
    reinit: str = '/api/v1/server/node/reinit'


@dataclass
class PayStatuses:
    pending: int = 1
    success: int = 2
    expired: int = 3
