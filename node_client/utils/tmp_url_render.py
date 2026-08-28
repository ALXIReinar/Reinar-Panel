from flatten_json import flatten
from jinja2 import Template


def generate_link_from_json(tmp_link: str, node_config_json: dict):
    """
    Собирает готовую конфиг-ссылку для клиента до этапа подстановки user_uuid перед самой выдачей подписки

    :param tmp_link: vless://{user___uuid}@{{node___address}}:{{inbounds___0___port}}?encryption=none...type={{inbounds___0___streamSettings___network}}#{{node___title}}
    :param node_config_json: конфиг файл ноды
    :param node_ip_or_domain: публичный ip ноды или домен для. Необходим в пользовательском конфиге
    :param node_title:
    :return: vless://{user_uuid}@192.168.1.100:443?encryption=none&flow=xtls-rprx-vision&security=reality&sni=ads.x5.ru&fp=chrome&pbk=ABC123...&sid=709c400f8da05efa&type=tcp#MyNode
    """

    "делаем все элементы плоскими"
    flat_config = flatten(node_config_json, separator='___')

    "Рендерим двойные плейсхолдеры '{{v___0___item}}' "
    template = Template(tmp_link)
    config_url = template.render(flat_config)
    return True, config_url