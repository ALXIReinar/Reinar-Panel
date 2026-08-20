"""
Helper функции для работы с user_obj в тестах

Скопировано из web.sub.api.handlers.prepare_func для независимости от web микросервиса
"""


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
        user_sub_id: ID подписки пользователя (опционально)

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
        user_uuid: str,
        user_sub_id: int | str,
        required_user_data_obj: dict,
        constant_user_data_obj: dict,
        constant_node_data_obj: dict,
):
    """
    Собирает готовый объект пользователя (суперобъект) из шаблон-скриптов
    
    Используется для создания user_obj который затем:
    - Передаётся в extractor_script инжекторов
    - Используется в prepare_sub скриптах
    
    Args:
        user_uuid: UUID пользователя
        user_sub_id: ID подписки пользователя
        required_user_data_obj: Шаблон с плейсхолдерами {USER_UUID}, {USER_SUB_ID}
        constant_user_data_obj: Константные данные пользователя (flow, level, etc.)
        constant_node_data_obj: Константные данные ноды (public_key, fp, etc.)
    
    Returns:
        tuple[bool, dict | str]: (success, user_obj | error_message)
    
    Example:
        >>> ok, user_obj = create_vpn_like_user(
        ...     user_uuid="abc-123",
        ...     user_sub_id=42,
        ...     required_user_data_obj={"user_uuid": "{USER_UUID}", "user_sub_id": "{USER_SUB_ID}"},
        ...     constant_user_data_obj={"flow": "xtls-rprx-vision", "level": 0},
        ...     constant_node_data_obj={"node_public_key": "key123", "sub_link_fp": "chrome"}
        ... )
        >>> print(user_obj)
        {
            'user_uuid': 'abc-123',
            'user_sub_id': '42',
            'flow': 'xtls-rprx-vision',
            'level': 0,
            'node_public_key': 'key123',
            'sub_link_fp': 'chrome'
        }
    """
    try:
        # 1. Подстановка значений в шаблон через плейсхолдеры
        required_user_obj = resolve_user_template(
            template=required_user_data_obj,
            uuid=user_uuid,
            user_sub_id=user_sub_id,
        )
        
        # 2. Объединяем все 3 data_obj в один суперобъект
        final_user_obj = {
            **required_user_obj,
            **constant_user_data_obj,
            **constant_node_data_obj,
        }
        
        return True, final_user_obj
    except Exception as e:
        return False, repr(e)
