"""
Unit тесты для админских хендлеров (bot/core/handlers/admin_commands.py).

Покрывает:
- MiddlewareAdmin: проверка доступа к админским командам
- reset_req_limit(): сброс rate limit пользователя
- flush_shop_cache(): очистка кэша магазина подписок

Использует настоящий Redis для реалистичного тестирования.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from aiogram.types import Message, User as TgUser, Chat
from datetime import datetime

from bot.core.handlers.admin_commands import MiddlewareAdmin, reset_req_limit, flush_shop_cache
from bot.core.utils.anything import RedisKeys
from bot.config_dir.config import env


# ============================================================================
# A. Тесты для MiddlewareAdmin - 7 тестов
# ============================================================================

@pytest.mark.asyncio
async def test_middleware_passes_non_command_messages():
    """Тест: middleware пропускает обычные сообщения (не команды)"""
    # Arrange
    middleware = MiddlewareAdmin()
    handler = AsyncMock(return_value="handler_result")
    
    user = TgUser(id=12345, username='regular_user', first_name='Test', is_bot=False)
    message = Message(
        message_id=1,
        date=datetime.now(),
        chat=Chat(id=12345, type='private'),
        from_user=user,
        text="Обычное сообщение без команды"
    )
    
    # Act
    result = await middleware(handler, message, {})
    
    # Assert
    handler.assert_called_once_with(message, {})
    assert result == "handler_result"


@pytest.mark.asyncio
async def test_middleware_passes_regular_commands():
    """Тест: middleware пропускает обычные команды (не админские)"""
    # Arrange
    middleware = MiddlewareAdmin()
    handler = AsyncMock(return_value="handler_result")
    
    user = TgUser(id=12345, username='regular_user', first_name='Test', is_bot=False)
    message = Message(
        message_id=2,
        date=datetime.now(),
        chat=Chat(id=12345, type='private'),
        from_user=user,
        text="/start"
    )
    
    # Act
    result = await middleware(handler, message, {})
    
    # Assert
    handler.assert_called_once_with(message, {})
    assert result == "handler_result"


@pytest.mark.asyncio
async def test_middleware_passes_admin_commands_for_admin():
    """Тест: middleware пропускает админские команды для админа"""
    # Arrange
    middleware = MiddlewareAdmin()
    handler = AsyncMock(return_value="handler_result")
    
    user = TgUser(id=env.admin_tg_id, username='admin', first_name='Admin', is_bot=False)
    message = Message(
        message_id=3,
        date=datetime.now(),
        chat=Chat(id=env.admin_tg_id, type='private'),
        from_user=user,
        text="/flush_shop_cache"
    )
    
    # Act
    result = await middleware(handler, message, {})
    
    # Assert
    handler.assert_called_once_with(message, {})
    assert result == "handler_result"


@pytest.mark.asyncio
async def test_middleware_blocks_admin_commands_for_non_admin():
    """Тест: middleware блокирует админские команды для не-админа"""
    # Arrange
    middleware = MiddlewareAdmin()
    handler = AsyncMock(return_value="handler_result")
    
    user = TgUser(id=99999, username='hacker', first_name='Hacker', is_bot=False)
    message = Message(
        message_id=4,
        date=datetime.now(),
        chat=Chat(id=99999, type='private'),
        from_user=user,
        text="/flush_shop_cache"
    )
    
    with patch.object(Message, 'answer', new_callable=AsyncMock) as mock_answer:
        # Act
        result = await middleware(handler, message, {})
        
        # Assert
        # 1. Handler НЕ вызван
        handler.assert_not_called()
        
        # 2. Возвращает None
        assert result is None
        
        # 3. Сообщение о блокировке отправлено
        mock_answer.assert_called_once()


@pytest.mark.asyncio
async def test_middleware_sends_warning_on_unauthorized_access():
    """Тест: middleware отправляет warning сообщение при несанкционированном доступе"""
    # Arrange
    middleware = MiddlewareAdmin()
    handler = AsyncMock()
    
    user = TgUser(id=88888, username='intruder', first_name='Intruder', is_bot=False)
    message = Message(
        message_id=5,
        date=datetime.now(),
        chat=Chat(id=88888, type='private'),
        from_user=user,
        text="/reset_req_limit 123456"
    )
    
    with patch.object(Message, 'answer', new_callable=AsyncMock) as mock_answer:
        # Act
        await middleware(handler, message, {})
        
        # Assert
        mock_answer.assert_called_once_with('Операция доступна только администратору')


@pytest.mark.asyncio
@patch('bot.core.handlers.admin_commands.log_event')
async def test_middleware_logs_unauthorized_access_attempts(mock_log_event):
    """Тест: middleware логирует попытки несанкционированного доступа"""
    # Arrange
    middleware = MiddlewareAdmin()
    handler = AsyncMock()
    
    user = TgUser(id=77777, username='attacker', first_name='Attacker', is_bot=False)
    message = Message(
        message_id=6,
        date=datetime.now(),
        chat=Chat(id=77777, type='private'),
        from_user=user,
        text="/flush_shop_cache"
    )
    
    with patch.object(Message, 'answer', new_callable=AsyncMock):
        # Act
        await middleware(handler, message, {})
        
        # Assert
        mock_log_event.assert_called_once()
        call_args = mock_log_event.call_args
        
        # Проверяем что в логе есть информация о попытке доступа
        assert '77777' in call_args[0][0]  # tg_id
        assert 'attacker' in call_args[0][0]  # username
        assert call_args[1]['level'] == 'WARNING'


@pytest.mark.asyncio
async def test_middleware_handles_commands_with_parameters():
    """Тест: middleware корректно обрабатывает команды с параметрами"""
    # Arrange
    middleware = MiddlewareAdmin()
    handler = AsyncMock(return_value="handler_result")
    
    user = TgUser(id=env.admin_tg_id, username='admin', first_name='Admin', is_bot=False)
    message = Message(
        message_id=7,
        date=datetime.now(),
        chat=Chat(id=env.admin_tg_id, type='private'),
        from_user=user,
        text="/reset_req_limit 123456"
    )
    
    # Act
    result = await middleware(handler, message, {})
    
    # Assert
    handler.assert_called_once_with(message, {})
    assert result == "handler_result"


# ============================================================================
# B. Тесты для reset_req_limit() - 6 тестов
# ============================================================================

@pytest.mark.asyncio
async def test_reset_req_limit_success(redis_client):
    """Тест: успешно сбрасывает лимит при валидном tg_id"""
    # Arrange
    user_tg_id = 555555
    redis_key = RedisKeys.rate_limit(user_tg_id)
    
    # Создаём запись в Redis
    await redis_client.set(redis_key, "5", ex=60)
    
    user = TgUser(id=env.admin_tg_id, username='admin', first_name='Admin', is_bot=False)
    message = Message(
        message_id=10,
        date=datetime.now(),
        chat=Chat(id=env.admin_tg_id, type='private'),
        from_user=user,
        text=f"/reset_req_limit {user_tg_id}"
    )
    
    with patch.object(Message, 'answer', new_callable=AsyncMock) as mock_answer:
        # Act
        await reset_req_limit(message, redis_client)
        
        # Assert
        # 1. Ключ удалён из Redis
        exists = await redis_client.exists(redis_key)
        assert exists == 0
        
        # 2. Успешное сообщение отправлено
        mock_answer.assert_called_once()
        call_text = mock_answer.call_args[0][0]
        assert '✅ Выполнено' in call_text
        assert str(user_tg_id) in call_text


@pytest.mark.asyncio
async def test_reset_req_limit_deletes_redis_key(redis_client):
    """Тест: корректно удаляет ключ из Redis"""
    # Arrange
    user_tg_id = 666666
    redis_key = RedisKeys.rate_limit(user_tg_id)
    
    # Предварительно создаём ключ
    await redis_client.set(redis_key, "3", ex=60)
    assert await redis_client.exists(redis_key) == 1
    
    user = TgUser(id=env.admin_tg_id, username='admin', first_name='Admin', is_bot=False)
    message = Message(
        message_id=11,
        date=datetime.now(),
        chat=Chat(id=env.admin_tg_id, type='private'),
        from_user=user,
        text=f"/reset_req_limit {user_tg_id}"
    )
    
    with patch.object(Message, 'answer', new_callable=AsyncMock):
        # Act
        await reset_req_limit(message, redis_client)
        
        # Assert: ключ больше не существует
        exists = await redis_client.exists(redis_key)
        assert exists == 0


@pytest.mark.asyncio
async def test_reset_req_limit_sends_success_message(redis_client):
    """Тест: отправляет успешное сообщение при сбросе"""
    # Arrange
    user_tg_id = 777777
    redis_key = RedisKeys.rate_limit(user_tg_id)
    await redis_client.set(redis_key, "10", ex=60)
    
    user = TgUser(id=env.admin_tg_id, username='admin', first_name='Admin', is_bot=False)
    message = Message(
        message_id=12,
        date=datetime.now(),
        chat=Chat(id=env.admin_tg_id, type='private'),
        from_user=user,
        text=f"/reset_req_limit {user_tg_id}"
    )
    
    with patch.object(Message, 'answer', new_callable=AsyncMock) as mock_answer:
        # Act
        await reset_req_limit(message, redis_client)
        
        # Assert
        mock_answer.assert_called_once()
        call_text = mock_answer.call_args[0][0]
        assert '✅ Выполнено' in call_text
        assert 'Лимит запросов' in call_text
        assert str(user_tg_id) in call_text
        assert 'сброшен' in call_text


@pytest.mark.asyncio
async def test_reset_req_limit_error_missing_tg_id(redis_client):
    """Тест: отправляет ошибку если tg_id отсутствует"""
    # Arrange
    user = TgUser(id=env.admin_tg_id, username='admin', first_name='Admin', is_bot=False)
    message = Message(
        message_id=13,
        date=datetime.now(),
        chat=Chat(id=env.admin_tg_id, type='private'),
        from_user=user,
        text="/reset_req_limit"  # Без параметра
    )
    
    with patch.object(Message, 'answer', new_callable=AsyncMock) as mock_answer:
        # Act
        await reset_req_limit(message, redis_client)
        
        # Assert
        mock_answer.assert_called_once()
        call_text = mock_answer.call_args[0][0]
        assert '❌ Не выполнено' in call_text
        assert 'корректный числовой' in call_text
        assert 'tg_id' in call_text


@pytest.mark.asyncio
async def test_reset_req_limit_error_invalid_tg_id(redis_client):
    """Тест: отправляет ошибку если tg_id не число"""
    # Arrange
    user = TgUser(id=env.admin_tg_id, username='admin', first_name='Admin', is_bot=False)
    message = Message(
        message_id=14,
        date=datetime.now(),
        chat=Chat(id=env.admin_tg_id, type='private'),
        from_user=user,
        text="/reset_req_limit abc123"  # Невалидный tg_id
    )
    
    with patch.object(Message, 'answer', new_callable=AsyncMock) as mock_answer:
        # Act
        await reset_req_limit(message, redis_client)
        
        # Assert
        mock_answer.assert_called_once()
        call_text = mock_answer.call_args[0][0]
        assert '❌ Не выполнено' in call_text
        assert 'корректный числовой' in call_text


@pytest.mark.asyncio
async def test_reset_req_limit_error_user_not_found_in_redis(redis_client):
    """Тест: отправляет ошибку если пользователь не найден в Redis"""
    # Arrange
    user_tg_id = 999999  # Не существует в Redis
    
    user = TgUser(id=env.admin_tg_id, username='admin', first_name='Admin', is_bot=False)
    message = Message(
        message_id=15,
        date=datetime.now(),
        chat=Chat(id=env.admin_tg_id, type='private'),
        from_user=user,
        text=f"/reset_req_limit {user_tg_id}"
    )
    
    with patch.object(Message, 'answer', new_callable=AsyncMock) as mock_answer:
        # Act
        await reset_req_limit(message, redis_client)
        
        # Assert
        mock_answer.assert_called_once()
        call_text = mock_answer.call_args[0][0]
        assert '❌ Не выполнено' in call_text
        assert 'не существует в Redis' in call_text
        assert str(user_tg_id) in call_text


# ============================================================================
# C. Тесты для flush_shop_cache() - 4 теста
# ============================================================================

@pytest.mark.asyncio
async def test_flush_shop_cache_success(redis_client):
    """Тест: успешно очищает кэш магазина"""
    # Arrange
    redis_key = RedisKeys.shop_sub_plans
    
    # Создаём кэш в Redis
    import orjson
    test_data = [{'id': 1, 'title': 'Basic Plan'}]
    await redis_client.set(redis_key, orjson.dumps(test_data))
    
    user = TgUser(id=env.admin_tg_id, username='admin', first_name='Admin', is_bot=False)
    message = Message(
        message_id=20,
        date=datetime.now(),
        chat=Chat(id=env.admin_tg_id, type='private'),
        from_user=user,
        text="/flush_shop_cache"
    )
    
    with patch.object(Message, 'answer', new_callable=AsyncMock) as mock_answer:
        # Act
        await flush_shop_cache(message, redis_client)
        
        # Assert
        # 1. Ключ удалён из Redis
        exists = await redis_client.exists(redis_key)
        assert exists == 0
        
        # 2. Успешное сообщение отправлено
        mock_answer.assert_called_once()
        call_text = mock_answer.call_args[0][0]
        assert '✅ Выполнено' in call_text
        assert 'Кэш тарифных планов магазина очищен' in call_text


@pytest.mark.asyncio
async def test_flush_shop_cache_deletes_redis_key(redis_client):
    """Тест: корректно удаляет ключ из Redis"""
    # Arrange
    redis_key = RedisKeys.shop_sub_plans
    
    # Предварительно создаём ключ
    import orjson
    await redis_client.set(redis_key, orjson.dumps([{'id': 2}]))
    assert await redis_client.exists(redis_key) == 1
    
    user = TgUser(id=env.admin_tg_id, username='admin', first_name='Admin', is_bot=False)
    message = Message(
        message_id=21,
        date=datetime.now(),
        chat=Chat(id=env.admin_tg_id, type='private'),
        from_user=user,
        text="/flush_shop_cache"
    )
    
    with patch.object(Message, 'answer', new_callable=AsyncMock):
        # Act
        await flush_shop_cache(message, redis_client)
        
        # Assert: ключ больше не существует
        exists = await redis_client.exists(redis_key)
        assert exists == 0


@pytest.mark.asyncio
async def test_flush_shop_cache_sends_success_message(redis_client):
    """Тест: отправляет успешное сообщение при очистке"""
    # Arrange
    redis_key = RedisKeys.shop_sub_plans
    import orjson
    await redis_client.set(redis_key, orjson.dumps([{'id': 3}]))
    
    user = TgUser(id=env.admin_tg_id, username='admin', first_name='Admin', is_bot=False)
    message = Message(
        message_id=22,
        date=datetime.now(),
        chat=Chat(id=env.admin_tg_id, type='private'),
        from_user=user,
        text="/flush_shop_cache"
    )
    
    with patch.object(Message, 'answer', new_callable=AsyncMock) as mock_answer:
        # Act
        await flush_shop_cache(message, redis_client)
        
        # Assert
        mock_answer.assert_called_once()
        call_text = mock_answer.call_args[0][0]
        assert '✅ Выполнено' in call_text
        assert 'Кэш тарифных планов магазина очищен' in call_text


@pytest.mark.asyncio
async def test_flush_shop_cache_error_key_not_found(redis_client):
    """Тест: отправляет ошибку если ключ не найден"""
    # Arrange
    redis_key = RedisKeys.shop_sub_plans
    
    # Убеждаемся что ключа нет в Redis
    await redis_client.delete(redis_key)
    
    user = TgUser(id=env.admin_tg_id, username='admin', first_name='Admin', is_bot=False)
    message = Message(
        message_id=23,
        date=datetime.now(),
        chat=Chat(id=env.admin_tg_id, type='private'),
        from_user=user,
        text="/flush_shop_cache"
    )
    
    with patch.object(Message, 'answer', new_callable=AsyncMock) as mock_answer:
        # Act
        await flush_shop_cache(message, redis_client)
        
        # Assert
        mock_answer.assert_called_once()
        call_text = mock_answer.call_args[0][0]
        assert '❌ Не выполнено' in call_text
        assert 'не найден в Redis' in call_text
