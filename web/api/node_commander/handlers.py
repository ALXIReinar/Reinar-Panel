"""
Утилиты для работы с шаблонами пользовательских объектов в конфигах протоколов
"""


def resolve_user_template(
        template: dict,
        uuid: str,
        tg_username: str | None = None,
        additional_fields: dict | None = None
) -> dict:
    """
    Подставляет значения в шаблон пользователя

    Поддерживаемые маркеры:
    - {USER_UUID} → uuid пользователя
    - {USER_TG_USERNAME} → telegram username
    - {USER_CUSTOM:field_name} → значение из additional_fields['field_name']
    - Обычное значение (без {}) → используется как есть

    Args:
        template: Шаблон из required_user_data_obj
        uuid: UUID пользователя (обязательно)
        tg_username: Telegram username (опционально)
        additional_fields: Дополнительные поля (опционально)

    Returns:
        dict: Разрешённый шаблон с подставленными значениями

    Raises:
        ValueError: Если требуемое поле отсутствует

    Examples:
        >>> template = {"id": "{USER_UUID}", "email": "{USER_TG_USERNAME}"}
        >>> resolve_user_template(template, "abc-123", "john_doe")
        {"id": "abc-123", "email": "john_doe"}

        >>> template = {"password": "{USER_UUID}"}
        >>> resolve_user_template(template, "abc-123")
        {"password": "abc-123"}

        >>> template = {"PublicKey": "{USER_CUSTOM:public_key}"}
        >>> resolve_user_template(template, "abc-123", additional_fields={"public_key": "key123"})
        {"PublicKey": "key123"}
    """
    if additional_fields is None:
        additional_fields = {}

    resolved = {}

    markers_map = {
        '{USER_UUID}': uuid,
        '{USER_TG_USERNAME}': tg_username,
    }
    if '{USER_TG_USERNAME}' in set(template.values()) and tg_username is None:
        raise ValueError(
            f"Одно из кастомных полей требует tg_username (плейсхолдер {{USER_TG_USERNAME}}), "
            f"но оно не передано в запросе"
        )

    for key, value in template.items():
        # Если значение не строка, используем как есть
        if not isinstance(value, str):
            resolved[key] = value
            continue

        # Подстановка маркеров
        if value in set(template.values()):
            resolved[key] = markers_map[value] # "custom_key": "{USER_UUID}" --> "{USER_UUID}": tg_username --> "custom_key": tg_username


        elif value.startswith('{USER_CUSTOM:') and value.endswith('}'):
            # Извлекаем имя поля: {USER_CUSTOM:field_name} → field_name
            field_name = value[13:-1]

            if field_name not in additional_fields:
                raise ValueError(
                    f"Поле '{key}' требует additional_fields['{field_name}'] "
                    f"(маркер {{USER_CUSTOM:{field_name}}}), но оно не передано в запросе"
                )
            resolved[key] = additional_fields[field_name]

        else:
            # Обычное значение или неизвестный маркер - используем как есть
            resolved[key] = value

    return resolved
