from dataclasses import dataclass


@dataclass
class TgBotApi:
    send_message: str = 'https://api.telegram.org/bot{}/sendMessage'


@dataclass
class DeleteReasons:
    sub_revoke: str = 'sub_revoke'
    admin_bulk_delete: str = 'admin_bulk_delete'

@dataclass
class AddReasons:
    ...

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

@dataclass
class NodeUris:
    proto_core_bulk_action: str = '/api/v1/server/proto_core/user/bulk/action' # Experimental. Ещё не добавлено  на нод клиент

    get_metrics: str = '/api/v1/server/node/metrics'


@dataclass
class PayStatuses:
    pending: int = 1
    success: int = 2
    expired: int = 3