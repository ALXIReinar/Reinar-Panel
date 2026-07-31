"""
Тесты для rate_limiter декоратора.

Проверяет корректность ограничения частоты запросов для Message и CallbackQuery.
"""

import pytest
from unittest.mock import AsyncMock, patch
from aiogram.types import Message, CallbackQuery, User as TgUser, Chat
from datetime import datetime

from bot.core.utils.rate_limiter import rate_limit
from bot.core.utils.anything import RedisKeys


# ============================================================================
# A. Успешные сценарии - 4 теста
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_rate_limit_allows_within_limit(mock_answer, redis_client):
    """Тест: rate_limiter пропускает запросы в пределах лимита"""
    @rate_limit(max_requests=5, window_seconds=60)
    async def mock_handler(message: Message, redis, *args, **kwargs):
        return "success"
    
    user = TgUser(id=111, username="test", first_name="Test", last_name="User", is_bot=False)
    message = Message(message_id=1, date=datetime.now(), chat=Chat(id=111, type="private"), from_user=user)
    
    # Отправляем 3 запроса (в пределах лимита 5)
    for i in range(3):
        result = await mock_handler(message, redis_client)
        assert result == "success"
    
    # Сообщение о превышении НЕ отправлено
    mock_answer.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.integration
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_rate_limit_first_request_always_passes(mock_answer, redis_client):
    """Тест: первый запрос всегда проходит"""
    @rate_limit(max_requests=1, window_seconds=60)
    async def mock_handler(message: Message, redis, *args, **kwargs):
        return "first"
    
    user = TgUser(id=222, username="first", first_name="First", last_name="Test", is_bot=False)
    message = Message(message_id=2, date=datetime.now(), chat=Chat(id=222, type="private"), from_user=user)
    
    result = await mock_handler(message, redis_client)
    
    assert result == "first"
    mock_answer.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.integration
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_rate_limit_different_users_independent(mock_answer, redis_client):
    """Тест: лимиты независимы для разных пользователей"""
    @rate_limit(max_requests=2, window_seconds=60)
    async def mock_handler(message: Message, redis, *args, **kwargs):
        return "success"
    
    user1 = TgUser(id=333, username="user1", first_name="User", last_name="One", is_bot=False)
    user2 = TgUser(id=444, username="user2", first_name="User", last_name="Two", is_bot=False)
    
    msg1 = Message(message_id=3, date=datetime.now(), chat=Chat(id=333, type="private"), from_user=user1)
    msg2 = Message(message_id=4, date=datetime.now(), chat=Chat(id=444, type="private"), from_user=user2)
    
    # Каждый пользователь отправляет по 2 запроса
    assert await mock_handler(msg1, redis_client) == "success"
    assert await mock_handler(msg1, redis_client) == "success"
    assert await mock_handler(msg2, redis_client) == "success"
    assert await mock_handler(msg2, redis_client) == "success"
    
    mock_answer.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.integration
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_rate_limit_handler_return_value(mock_answer, redis_client):
    """Тест: декоратор возвращает результат хэндлера"""
    @rate_limit(max_requests=10, window_seconds=60)
    async def mock_handler(message: Message, redis, custom_arg):
        return f"result_{custom_arg}"
    
    user = TgUser(id=555, username="return", first_name="Return", last_name="Test", is_bot=False)
    message = Message(message_id=5, date=datetime.now(), chat=Chat(id=555, type="private"), from_user=user)
    
    result = await mock_handler(message, redis_client, custom_arg="test")
    
    assert result == "result_test"


# ============================================================================
# B. Блокировка избыточных запросов - 3 теста
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_rate_limit_blocks_excess_requests(mock_answer, redis_client):
    """Тест: rate_limiter блокирует запросы сверх лимита"""
    @rate_limit(max_requests=3, window_seconds=60)
    async def mock_handler(message: Message, redis, *args, **kwargs):
        return "success"
    
    user = TgUser(id=666, username="spammer", first_name="Spam", last_name="User", is_bot=False)
    message = Message(message_id=6, date=datetime.now(), chat=Chat(id=666, type="private"), from_user=user)
    
    # Отправляем 5 запросов (лимит 3)
    results = []
    for i in range(5):
        result = await mock_handler(message, redis_client)
        results.append(result)
    
    # Первые 3 запроса прошли, остальные заблокированы
    assert results[0] == "success"
    assert results[1] == "success"
    assert results[2] == "success"
    assert results[3] is None  # Заблокирован
    assert results[4] is None  # Заблокирован


@pytest.mark.asyncio
@pytest.mark.integration
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_rate_limit_sends_warning_message(mock_answer, redis_client):
    """Тест: rate_limiter отправляет сообщение о превышении лимита"""
    @rate_limit(max_requests=2, window_seconds=60)
    async def mock_handler(message: Message, redis, *args, **kwargs):
        return "success"
    
    user = TgUser(id=777, username="warning", first_name="Warning", last_name="Test", is_bot=False)
    message = Message(message_id=7, date=datetime.now(), chat=Chat(id=777, type="private"), from_user=user)
    
    # 3 запроса (лимит 2)
    await mock_handler(message, redis_client)
    await mock_handler(message, redis_client)
    await mock_handler(message, redis_client)  # Превышен лимит
    
    # Проверяем что сообщение было отправлено
    mock_answer.assert_called_once()
    call_args = mock_answer.call_args[0][0]
    assert "Слишком много запросов" in call_args or "запросов" in call_args.lower()


@pytest.mark.asyncio
@pytest.mark.integration
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_rate_limit_returns_none_when_blocked(mock_answer, redis_client):
    """Тест: декоратор возвращает None при блокировке"""
    @rate_limit(max_requests=1, window_seconds=60)
    async def mock_handler(message: Message, redis, *args, **kwargs):
        return "should_not_return"
    
    user = TgUser(id=888, username="blocked", first_name="Blocked", last_name="Test", is_bot=False)
    message = Message(message_id=8, date=datetime.now(), chat=Chat(id=888, type="private"), from_user=user)
    
    first = await mock_handler(message, redis_client)
    second = await mock_handler(message, redis_client)  # Заблокирован
    
    assert first == "should_not_return"
    assert second is None


# ============================================================================
# C. Работа с Redis - 4 теста
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_rate_limit_redis_key_format(mock_answer, redis_client):
    """Тест: rate_limiter создаёт ключ в формате RedisKeys.rate_limit()"""
    @rate_limit(max_requests=5, window_seconds=60)
    async def mock_handler(message: Message, redis, *args, **kwargs):
        return "success"
    
    user = TgUser(id=99999, username="key_test", first_name="Key", last_name="Test", is_bot=False)
    message = Message(message_id=9, date=datetime.now(), chat=Chat(id=99999, type="private"), from_user=user)
    
    await mock_handler(message, redis_client)
    
    # Проверяем что ключ существует (используем RedisKeys для правильного формата)
    key = RedisKeys.rate_limit(99999)
    exists = await redis_client.exists(key)
    assert exists == 1


@pytest.mark.asyncio
@pytest.mark.integration
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_rate_limit_sets_ttl(mock_answer, redis_client):
    """Тест: rate_limiter устанавливает TTL = window_seconds"""
    @rate_limit(max_requests=5, window_seconds=10)
    async def mock_handler(message: Message, redis, *args, **kwargs):
        return "success"
    
    user = TgUser(id=88888, username="ttl_test", first_name="TTL", last_name="Test", is_bot=False)
    message = Message(message_id=10, date=datetime.now(), chat=Chat(id=88888, type="private"), from_user=user)
    
    await mock_handler(message, redis_client)
    
    key = RedisKeys.rate_limit(88888)
    ttl = await redis_client.ttl(key)
    
    assert ttl > 0
    assert ttl <= 10


@pytest.mark.asyncio
@pytest.mark.integration
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_rate_limit_uses_pipeline(mock_answer, redis_client):
    """Тест: rate_limiter использует Redis pipeline для атомарности"""
    @rate_limit(max_requests=5, window_seconds=60)
    async def mock_handler(message: Message, redis, *args, **kwargs):
        return "success"
    
    user = TgUser(id=77777, username="pipe_test", first_name="Pipe", last_name="Test", is_bot=False)
    message = Message(message_id=11, date=datetime.now(), chat=Chat(id=77777, type="private"), from_user=user)
    
    await mock_handler(message, redis_client)
    
    # Pipeline должен создать ключ и установить TTL атомарно
    key = RedisKeys.rate_limit(77777)
    count = await redis_client.get(key)
    ttl = await redis_client.ttl(key)
    
    assert int(count) == 1
    assert ttl > 0


@pytest.mark.asyncio
@pytest.mark.integration
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_rate_limit_increments_counter(mock_answer, redis_client):
    """Тест: rate_limiter инкрементирует счётчик при каждом запросе"""
    @rate_limit(max_requests=10, window_seconds=60)
    async def mock_handler(message: Message, redis, *args, **kwargs):
        return "success"
    
    user = TgUser(id=66666, username="incr_test", first_name="Incr", last_name="Test", is_bot=False)
    message = Message(message_id=12, date=datetime.now(), chat=Chat(id=66666, type="private"), from_user=user)
    
    for i in range(3):
        await mock_handler(message, redis_client)
    
    key = RedisKeys.rate_limit(66666)
    count = await redis_client.get(key)
    
    assert int(count) == 3


# ============================================================================
# D. Граничные случаи - 4 теста
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_rate_limit_exact_limit(mock_answer, redis_client):
    """Тест: ровно max_requests запросов проходят"""
    @rate_limit(max_requests=4, window_seconds=60)
    async def mock_handler(message: Message, redis, *args, **kwargs):
        return "success"
    
    user = TgUser(id=55555, username="exact", first_name="Exact", last_name="Test", is_bot=False)
    message = Message(message_id=13, date=datetime.now(), chat=Chat(id=55555, type="private"), from_user=user)
    
    results = []
    for i in range(5):
        result = await mock_handler(message, redis_client)
        results.append(result)
    
    # Первые 4 прошли, 5-й заблокирован
    assert all(r == "success" for r in results[:4])
    assert results[4] is None


@pytest.mark.asyncio
@pytest.mark.integration
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_rate_limit_custom_params(mock_answer, redis_client):
    """Тест: кастомные max_requests и window_seconds работают"""
    @rate_limit(max_requests=7, window_seconds=30)
    async def mock_handler(message: Message, redis, *args, **kwargs):
        return "custom"
    
    user = TgUser(id=44444, username="custom", first_name="Custom", last_name="Test", is_bot=False)
    message = Message(message_id=14, date=datetime.now(), chat=Chat(id=44444, type="private"), from_user=user)
    
    for i in range(7):
        result = await mock_handler(message, redis_client)
        assert result == "custom"
    
    # 8-й запрос заблокирован
    blocked = await mock_handler(message, redis_client)
    assert blocked is None


@pytest.mark.asyncio
@pytest.mark.integration
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_rate_limit_zero_limit(mock_answer, redis_client):
    """Тест: max_requests=0 блокирует всё после первого запроса"""
    @rate_limit(max_requests=0, window_seconds=60)
    async def mock_handler(message: Message, redis, *args, **kwargs):
        return "zero"
    
    user = TgUser(id=33333, username="zero", first_name="Zero", last_name="Test", is_bot=False)
    message = Message(message_id=15, date=datetime.now(), chat=Chat(id=33333, type="private"), from_user=user)
    
    first = await mock_handler(message, redis_client)
    
    # Первый запрос заблокирован (current_count=1 > max_requests=0)
    assert first is None


@pytest.mark.unit
def test_rate_limit_preserves_handler_signature():
    """Тест: декоратор сохраняет имя и docstring хэндлера (@wraps)"""
    @rate_limit(max_requests=5, window_seconds=60)
    async def my_custom_handler(message: Message, redis, *args, **kwargs):
        """Custom handler docstring"""
        return "test"
    
    assert my_custom_handler.__name__ == "my_custom_handler"
    assert my_custom_handler.__doc__ == "Custom handler docstring"


# ============================================================================
# E. CallbackQuery поддержка - 5 тестов
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_rate_limit_callback_within_limit(mock_answer, redis_client):
    """Тест: rate_limiter пропускает CallbackQuery в пределах лимита"""
    @rate_limit(max_requests=5, window_seconds=60)
    async def mock_handler(callback: CallbackQuery, redis, *args, **kwargs):
        return "callback_success"
    
    user = TgUser(id=11111, username="cb_test", first_name="CB", last_name="Test", is_bot=False)
    message = Message(message_id=16, date=datetime.now(), chat=Chat(id=11111, type="private"), from_user=user)
    callback = CallbackQuery(id="cb_id_1", from_user=user, chat_instance="ci", message=message, data="test")
    
    for i in range(3):
        result = await mock_handler(callback, redis_client)
        assert result == "callback_success"
    
    mock_answer.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.integration
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_rate_limit_callback_blocks_excess(mock_answer, redis_client):
    """Тест: rate_limiter блокирует избыточные CallbackQuery"""
    @rate_limit(max_requests=2, window_seconds=60)
    async def mock_handler(callback: CallbackQuery, redis, *args, **kwargs):
        return "success"
    
    user = TgUser(id=22222, username="cb_block", first_name="CB", last_name="Block", is_bot=False)
    message = Message(message_id=17, date=datetime.now(), chat=Chat(id=22222, type="private"), from_user=user)
    callback = CallbackQuery(id="cb_id_2", from_user=user, chat_instance="ci", message=message, data="test")
    
    results = []
    for i in range(4):
        result = await mock_handler(callback, redis_client)
        results.append(result)
    
    assert results[0] == "success"
    assert results[1] == "success"
    assert results[2] is None  # Заблокирован
    assert results[3] is None


@pytest.mark.asyncio
@pytest.mark.integration
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_rate_limit_callback_user_id_extraction(mock_answer, redis_client):
    """Тест: rate_limiter правильно извлекает user_id из callback.from_user"""
    @rate_limit(max_requests=5, window_seconds=60)
    async def mock_handler(callback: CallbackQuery, redis, *args, **kwargs):
        return "ok"
    
    user = TgUser(id=12345, username="extraction", first_name="Extract", last_name="Test", is_bot=False)
    bot_user = TgUser(id=99999, username="bot", first_name="Bot", last_name="", is_bot=True)
    
    # message.from_user - данные бота
    message = Message(message_id=18, date=datetime.now(), chat=Chat(id=12345, type="private"), from_user=bot_user)
    # callback.from_user - данные пользователя
    callback = CallbackQuery(id="cb_id_3", from_user=user, chat_instance="ci", message=message, data="test")
    
    await mock_handler(callback, redis_client)
    
    # Ключ создан для пользователя, НЕ для бота
    user_key = RedisKeys.rate_limit(12345)
    bot_key = RedisKeys.rate_limit(99999)
    
    assert await redis_client.exists(user_key) == 1
    assert await redis_client.exists(bot_key) == 0


@pytest.mark.asyncio
@pytest.mark.integration
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_rate_limit_callback_sends_answer(mock_answer, redis_client):
    """Тест: rate_limiter отправляет callback.answer() с ошибкой при блокировке"""
    @rate_limit(max_requests=1, window_seconds=60)
    async def mock_handler(callback: CallbackQuery, redis, *args, **kwargs):
        return "ok"
    
    user = TgUser(id=54321, username="answer_test", first_name="Answer", last_name="Test", is_bot=False)
    message = Message(message_id=19, date=datetime.now(), chat=Chat(id=54321, type="private"), from_user=user)
    callback = CallbackQuery(id="cb_id_4", from_user=user, chat_instance="ci", message=message, data="test")
    
    await mock_handler(callback, redis_client)  # 1-й запрос
    await mock_handler(callback, redis_client)  # 2-й запрос (заблокирован)
    
    # callback.answer вызван с show_alert=True
    mock_answer.assert_called_once()
    call_args = mock_answer.call_args
    assert "Слишком много запросов" in call_args[0][0]
    assert call_args[1].get('show_alert') is True


@pytest.mark.asyncio
@pytest.mark.integration
@patch.object(Message, 'answer', new_callable=AsyncMock)
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_rate_limit_mixed_message_callback(mock_callback_answer, mock_message_answer, redis_client):
    """Тест: Message и CallbackQuery от одного пользователя считаются вместе"""
    @rate_limit(max_requests=3, window_seconds=60)
    async def mock_handler(event, redis, *args, **kwargs):
        return "mixed"
    
    user = TgUser(id=98765, username="mixed", first_name="Mixed", last_name="Test", is_bot=False)
    
    message = Message(message_id=20, date=datetime.now(), chat=Chat(id=98765, type="private"), from_user=user)
    
    callback_msg = Message(message_id=21, date=datetime.now(), chat=Chat(id=98765, type="private"), from_user=user)
    callback = CallbackQuery(id="cb_id_5", from_user=user, chat_instance="ci", message=callback_msg, data="test")
    
    # 2 Message + 2 CallbackQuery (лимит 3)
    assert await mock_handler(message, redis_client) == "mixed"
    assert await mock_handler(message, redis_client) == "mixed"
    assert await mock_handler(callback, redis_client) == "mixed"
    assert await mock_handler(callback, redis_client) is None  # Заблокирован


# ============================================================================
# F. Интеграционные тесты (медленные) - 2 теста
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.slow
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_rate_limit_ttl_expiration(mock_answer, redis_client):
    """Тест: ключ удаляется после TTL (требует ожидания)"""
    import asyncio
    
    @rate_limit(max_requests=1, window_seconds=2)
    async def mock_handler(message: Message, redis, *args, **kwargs):
        return "expiring"
    
    user = TgUser(id=13579, username="expire", first_name="Expire", last_name="Test", is_bot=False)
    message = Message(message_id=22, date=datetime.now(), chat=Chat(id=13579, type="private"), from_user=user)
    
    await mock_handler(message, redis_client)  # 1-й запрос
    assert await mock_handler(message, redis_client) is None  # Заблокирован
    
    # Ждём истечения TTL
    await asyncio.sleep(3)
    
    # После истечения TTL лимит сброшен
    result = await mock_handler(message, redis_client)
    assert result == "expiring"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.slow
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_rate_limit_concurrent_requests(mock_answer, redis_client):
    """Тест: параллельные запросы корректно обрабатываются"""
    import asyncio
    
    @rate_limit(max_requests=5, window_seconds=60)
    async def mock_handler(message: Message, redis, *args, **kwargs):
        await asyncio.sleep(0.01)  # Имитация работы
        return "concurrent"
    
    user = TgUser(id=24680, username="concurrent", first_name="Concurrent", last_name="Test", is_bot=False)
    message = Message(message_id=23, date=datetime.now(), chat=Chat(id=24680, type="private"), from_user=user)
    
    # Отправляем 10 параллельных запросов
    tasks = [mock_handler(message, redis_client) for _ in range(10)]
    results = await asyncio.gather(*tasks)
    
    # Первые 5 прошли, остальные заблокированы
    passed = [r for r in results if r == "concurrent"]
    blocked = [r for r in results if r is None]
    
    assert len(passed) == 5
    assert len(blocked) == 5
