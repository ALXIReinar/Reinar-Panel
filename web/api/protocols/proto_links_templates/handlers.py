from urllib.parse import quote, urlsplit, urlencode, urlunsplit, parse_qsl

import orjson
from flatten_json import flatten
from jinja2 import Template
from pydantic import IPvAnyAddress


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
    if not tmp_link:
        return False, 'Url конфиг-ссылка не указана в шаблоне. Обновите шаблон протокола, который используется этой нодой'

    "Все ли кастомные spec попадут в ссылку"
    for spec_key in spec_keys_values.keys():
        if "{{" + spec_key + "}}" not in tmp_link:
            return False, f"Spec key: {spec_key} указан в кастомных параметрах, но отсутствует в ссылке-шаблоне"

    if isinstance(node_config_json, str):
        node_config_json = orjson.loads(node_config_json)

    flat_config = flatten(node_config_json, separator='___')

    # 1.1. При необходимости конвертируем домен в punycode или оставляем IP
    try:
        # Проверяем, является ли адрес валидным IPv4 или IPv6
        node_ip_or_domain = str(IPvAnyAddress(node_ip_or_domain))
    except ValueError:
        # Если это не IP, то считаем доменом. Конвертируем в punycode ( IDNA )
        try:
            node_ip_or_domain = node_ip_or_domain.encode('idna').decode('ascii')
        except UnicodeError:
            # На случай странных символов падем на стандартный quote
            node_ip_or_domain = quote(node_ip_or_domain)

    # 1.2. Собираем базовый контекст
    context = {
        **flat_config,
        **spec_keys_values,
        'node___address': node_ip_or_domain,
        'node___title': node_title,
    }
    # 2. Рендерим сырой URL через Jinja2
    template = Template(tmp_link)
    raw_url = template.render(context)

    # 3. Разбираем URL на компоненты и безопасно кодируем
    parsed = urlsplit(raw_url)

    # parse_qsl разбивает строку "a=1&b=2" на список кортежей [('a', '1'), ('b', '2')]
    # urlencode собирает это обратно в безопасный вид, энкодя все спецсимволы
    safe_query = urlencode(parse_qsl(parsed.query))

    # quote энкодит только fragment (#MyNode -> #My%20Node)
    safe_fragment = quote(parsed.fragment)

    # 4. Собираем итоговую ссылку
    final_url = urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        safe_query,
        safe_fragment
    ))
    
    # 5. Если в исходном шаблоне был fragment (#), но он пустой, urlunsplit удалит #
    # Нужно вернуть # в конец URL для корректного формата ссылки
    if '{{node___title}}' in tmp_link and not safe_fragment and not final_url.endswith('#'):
        final_url += '#'
    
    return True, final_url