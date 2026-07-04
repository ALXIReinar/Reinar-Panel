"""
Фабрики для создания тестовых данных
"""
import uuid as uuid_lib
from typing import Optional


def create_test_user(
    email: Optional[str] = None,
    uuid: Optional[str] = None,
    flow: str = "xtls-rprx-vision",
    level: int = 0
) -> dict:
    """
    Создаёт тестового пользователя для xray конфига
    
    Args:
        email: Email пользователя (генерируется если None)
        uuid: UUID пользователя (генерируется если None)
        flow: Flow для VLESS (по умолчанию xtls-rprx-vision)
        level: Уровень пользователя
    
    Returns:
        dict: Объект пользователя для конфига xray
    
    Example:
        >>> user = create_test_user()
        >>> user
        {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "email": "test_user_550e8400",
            "flow": "xtls-rprx-vision",
            "level": 0
        }
    """
    if uuid is None:
        uuid = str(uuid_lib.uuid4())
    
    if email is None:
        # Генерируем email на основе первых 8 символов UUID
        email = f"test_user_{uuid[:8]}"
    
    return {
        "id": uuid,
        "email": email,
        "flow": flow,
        "level": level
    }


def create_bulk_test_users(count: int, prefix: str = "bulk_user") -> list[dict]:
    """
    Создаёт список тестовых пользователей
    
    Args:
        count: Количество пользователей
        prefix: Префикс для email
    
    Returns:
        list[dict]: Список пользователей
    
    Example:
        >>> users = create_bulk_test_users(3, "test")
        >>> len(users)
        3
    """
    return [
        create_test_user(email=f"{prefix}_{i}")
        for i in range(count)
    ]
