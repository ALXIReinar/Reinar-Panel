import json
from urllib.parse import quote

from flatten_json import flatten
from jinja2 import Template


def generate_link_from_json(tmp_link: str, node_config_json: str | dict, spec_keys_values: dict, node_ip_or_domain: str, node_title: str):
    """
    Собирает готовую конфиг-ссылку для клиента до этапа подстановки user_uuid перед самой выдачей подписки

    :param tmp_link: vless://{user___uuid}@{{node___address}}:{{inbounds___0___port}}?encryption=none...type={{inbounds___0___streamSettings___network}}#{{node___title}}
    :param node_config_json: конфиг файл ноды
    :param spec_keys_values: значения, которые не лежат в конфиг-фалйе на ноде
    :param node_ip_or_domain: публичный ip ноды или домен для. Необходим в пользовательском конфиге
    :param node_title:
    :return: vless://{user_uuid}@192.168.1.100:443?encryption=none&flow=xtls-rprx-vision&security=reality&sni=ads.x5.ru&fp=chrome&pbk=ABC123...&sid=709c400f8da05efa&type=tcp#MyNode
    """
    "Проверяем зависимости перед генерацией ссылки"
    if tmp_link is None:
        return False, 'Url конфиг-ссылка не указана в шаблоне. Обновите шаблон протокола, который используется этой нодой'

    "Все ли кастомные spec попадут в ссылку"
    for spec_key in spec_keys_values.keys():
        if "{{" + spec_key + "}}" not in tmp_link:
            return False, f"Spec key: {spec_key} указан в кастомных параметрах, но отсутствует в ссылке-шаблоне"

    if isinstance(node_config_json, str):
        node_config_json = json.loads(node_config_json)

    flat_config = flatten(node_config_json, separator='___') # '___' используется против конфликтов с ключами с одним _ в файле-конфиге

    # 2. Собираем финальный контекст для Jinja2
    context = {
        **flat_config,
        **spec_keys_values,  # Значения, которые нельзя найти в конфиг-файле, например pbk для VLESS
        'node___address': node_ip_or_domain,
        'node___title': quote(node_title), # для красивого отображения флага страны сервера
    }

    # 3. Рендерим шаблон
    template = Template(tmp_link)
    return True, template.render(context)