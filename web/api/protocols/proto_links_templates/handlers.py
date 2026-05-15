import json
from urllib.parse import quote

from flatten_json import flatten
from jinja2 import Template


def generate_link_from_json(tmp_link: str, node_config_json: str | dict, json_separator: str, spec_keys_values: dict[str, str], node_title: str):
    """
    Собирает готовую конфиг-ссылку для клиента до этапа подстановки user_uuid перед самой выдачей подписки

    :param tmp_link: vless://{user_uuid}@{{node_ip}}:{{inbounds.0.port}}?encryption=none...type={{inbounds.0.streamSettings.network}}#{{node_title}}
    :param node_config_json: конфиг файл ноды
    :param json_separator: разделитель json файла
    :param spec_keys_values: значения, которые не лежат в конфиг-фалйе на ноде
    :param node_title:
    :return: vless://{user_uuid}@192.168.1.100:443?encryption=none&flow=xtls-rprx-vision&security=reality&sni=ads.x5.ru&fp=chrome&pbk=ABC123...&sid=709c400f8da05efa&type=tcp#MyNode
    """
    if isinstance(node_config_json, str):
        node_config_json = json.loads(node_config_json)

    flat_config = flatten(node_config_json, separator=json_separator)

    # 2. Собираем финальный контекст для Jinja2
    context = {
        **flat_config,
        **spec_keys_values,  # Значения, которые нельзя найти в конфиг-файле, например pbk для VLESS
        'node_title': quote(node_title), # для красивого отображения флага страны сервера
    }

    # 3. Рендерим шаблон
    template = Template(tmp_link)
    return template.render(context)