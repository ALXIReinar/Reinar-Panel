from dataclasses import dataclass


@dataclass
class RobokassaUrls:
    create_payment = 'https://auth.robokassa.ru/Merchant/Index.aspx' # Пользователь перейдёт на страницу робокассы для оплаты


@dataclass
class PayStatuses:
    pending: int = 1
    success: int = 2
    expired: int = 3

@dataclass
class Constants:

    @staticmethod
    def payment_robo_lock(csrf_token: str):
        return f'pay_lock:robo:{csrf_token}'


@dataclass
class NodeUris:
    proto_core_add_user: str = '/api/v1/server/proto_core/user/add'
    proto_core_delete_user: str = '/api/v1/server/proto_core/user/delete'
    proto_core_bulk_delete_users: str = '/api/v1/server/proto_core/user/bulk/delete'
    proto_core_bulk_add_users: str = '/api/v1/server/proto_core/user/bulk/add'
    get_metrics: str = '/api/v1/server/node/metrics'

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
class UserStatuses:
    not_connect: int = 1
    offline: int = 2
    online: int = 3
