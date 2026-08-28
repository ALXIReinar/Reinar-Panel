import base64
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse, quote

from pydantic import IPvAnyAddress


def error_messages_for_client(*messages: str):
    tmp = 'vless://00000000-0000-0000-0000-000000000000@127.0.0.1:443?encryption=none#{}'
    return [tmp.format(quote(msg)) for msg in messages]

def process2vpn_client_format(any_obj: str | list[str], description: str = None) -> str:
    if isinstance(any_obj, list):
        any_obj = '\n'.join(any_obj)
    if description is not None:
        any_obj = f"#note:{quote(description)}\n{any_obj}"
    return base64.b64encode(any_obj.encode()).decode()


def normalize_url(url: str) -> str:
    parsed = urlparse(url)

    query_params = parse_qsl(parsed.query, keep_blank_values=True)

    normalized_query = urlencode(query_params, quote_via=quote)

    return urlunparse(parsed._replace(query=normalized_query))


def urlsafe_address(node_ip_or_domain):
    try:
        # Проверяем, является ли адрес валидным IPv4 или IPv6
        node_ip_or_domain = str(IPvAnyAddress(node_ip_or_domain))
    except ValueError:
        # Если это не IP, то считаем доменом. Конвертируем в punycode (IDNA)
        try:
            node_ip_or_domain = node_ip_or_domain.encode('idna').decode('ascii')
        except (UnicodeError, UnicodeDecodeError):
            # Если punycode провалился - оставляем как есть
            # Клиент получит ошибку DNS при попытке подключения
            # ВАЖНО: НЕ используем quote() для hostname - это сломает DNS резолвинг
            pass
    return node_ip_or_domain


def resolve_user_template(
        template: dict,
        uuid: str,
        user_sub_id: int | None = None
) -> dict:
    """
    Подставляет значения в шаблон пользователя

    Поддерживаемые маркеры:
    - {USER_UUID} → uuid пользователя
    - {USER_SUB_ID} → id подписки пользователя. В json объекте преобразуется в str
    - Обычное значение (без {}) → используется как есть

    Args:
        template: Шаблон из required_user_data_obj
        uuid: UUID пользователя (обязательно)
        user_sub_id: Telegram username (опционально)

    Returns:
        dict: Разрешённый шаблон с подставленными значениями

    Raises:
        ValueError: Если требуется user_sub_id, но он не передан

    Examples:
        >>> template = {"id": "{USER_UUID}", "email": "{USER_SUB_ID}"}
        >>> resolve_user_template(template, "abc-123", 1)
        {"id": "abc-123", "email": "1"}

        >>> template = {"password": "{USER_UUID}", "level": 5}
        >>> resolve_user_template(template, "abc-123")
        {"password": "abc-123", "level": 5}
    """
    markers_map = {
        '{USER_UUID}': uuid,
        '{USER_SUB_ID}': str(user_sub_id),
    }

    # Проверяем что user_sub_id передан, если он требуется в шаблоне
    if '{USER_SUB_ID}' in template.values() and user_sub_id is None:
        raise ValueError(
            f"Одно из полей шаблона требует user_sub_id (плейсхолдер {{USER_SUB_ID}}), "
            f"но оно не передано"
        )

    resolved = {}
    for key, value in template.items():
        # Если значение не строка, используем как есть
        if not isinstance(value, str):
            resolved[key] = value
            continue

        # Подстановка маркеров, если значение совпадает с ключом
        if value in markers_map:
            resolved[key] = markers_map[value]
        else:
            # Обычное значение - используем как есть
            resolved[key] = value

    return resolved


def create_vpn_like_user(
        user_uuid,
        user_sub_id,
        required_user_data_obj: dict,
        constant_user_data_obj: dict,
        constant_node_data_obj: dict,
):
    """Собирает готовый объект пользователя для впн-ядра из шаблон-скриптов"""

    "1. Подстановка значений в шаблон через плейсхолдеры"
    try:
        required_user_obj = resolve_user_template(
            template=required_user_data_obj,
            uuid=user_uuid,
            user_sub_id=user_sub_id,
        )
        final_user_obj = {
            **required_user_obj,
            **constant_user_data_obj,
            **constant_node_data_obj,
        }
        return True, final_user_obj
    except Exception as e:
        return False, repr(e)