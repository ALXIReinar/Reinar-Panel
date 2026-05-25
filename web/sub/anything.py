from dataclasses import dataclass


@dataclass
class RobokassaUrls:
    create_payment = 'https://auth.robokassa.ru/Merchant/Index.aspx' # Пользователь перейдёт на страницу робокассы для оплаты


@dataclass
class Constants:

    @staticmethod
    def payment_robo_lock(csrf_token: str):
        return f'pay_lock:robo:{csrf_token}'


@dataclass
class NodeUris:
    proto_core_add_user: str = '/api/v1/server/node/proto_core/user/add'
    proto_core_delete_user: str = '/api/v1/server/node/proto_core/user/delete'

class CoreProtoActions:
    add: int = 1
    delete: int = 2

    word_add: str = 'add'
    word_delete: str = 'delete'

    name2id: dict[str, int] = {
        'add': 1,
        'delete': 2,
    }