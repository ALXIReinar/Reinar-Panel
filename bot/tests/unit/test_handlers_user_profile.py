"""
Тесты для хэндлера user_profile_handler.py (bot/core/handlers/user_profile_handler.py).

Проверяет корректность работы show_user_profile():
- Вызов API для получения данных пользователя
- Отправка сообщения с клавиатурой
- Обработка ошибок API
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from aiogram.types import Message, User as TgUser, Chat
from datetime import datetime

from bot.core.handlers.user_profile_handler import show_user_profile
from bot.core.utils.schemas import UserSchema


# ============================================================================
# show_user_profile() - 4 теста
# ============================================================================

@pytest.mark.asyncio
@patch('bot.core.handlers.user_profile_handler.profile_kb')
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_show_user_profile_calls_get_user_info(mock_answer, mock_profile_kb, redis_client):
    """Тест: show_user_profile вызывает get_user_info() с правильным tg_id"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    user_data = {
        'id': 1,
        'registered_at': '2023-12-01T10:00:00',
        'sub_count': 2
    }
    
    fake_session = FakeAiohttpSession(json_data=user_data, status=200)
    conn = SubServiceConn(fake_session)
    mock_profile_kb.return_value = MagicMock()
    
    user = TgUser(id=123456, username='test_user', first_name='Test', last_name='User', is_bot=False)
    message = Message(message_id=1, date=datetime.now(), chat=Chat(id=123456, type='private'), from_user=user)
    
    # Act
    await show_user_profile(message, redis_client, conn)
    
    # Assert: проверяем что вызван get_user_info с правильным tg_id
    assert len(fake_session.request_calls) == 1
    call = fake_session.request_calls[0]
    assert call['method'] == 'GET'
    assert call['kwargs']['params']['tg_id'] == 123456


@pytest.mark.asyncio
@patch('bot.core.handlers.user_profile_handler.profile_kb')
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_show_user_profile_sends_message_with_keyboard(mock_answer, mock_profile_kb, redis_client):
    """Тест: show_user_profile отправляет сообщение с клавиатурой profile_kb()"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    user_data = {
        'id': 1,
        'registered_at': '2023-12-01T10:00:00',
        'sub_count': 1
    }
    
    fake_session = FakeAiohttpSession(json_data=user_data, status=200)
    conn = SubServiceConn(fake_session)
    
    mock_keyboard = MagicMock()
    mock_profile_kb.return_value = mock_keyboard
    
    user = TgUser(id=654321, username='profile_user', first_name='Profile', last_name='User', is_bot=False)
    message = Message(message_id=2, date=datetime.now(), chat=Chat(id=654321, type='private'), from_user=user)
    
    # Act
    await show_user_profile(message, redis_client, conn)
    
    # Assert
    # 1. Проверяем что вызван profile_kb
    mock_profile_kb.assert_called_once()
    
    # 2. Проверяем что сообщение отправлено
    mock_answer.assert_called_once()
    
    # 3. Проверяем что клавиатура передана
    call_kwargs = mock_answer.call_args[1]
    assert call_kwargs['reply_markup'] == mock_keyboard


@pytest.mark.asyncio
@patch('bot.core.handlers.user_profile_handler.profile_kb')
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_show_user_profile_user_schema_creation(mock_answer, mock_profile_kb, redis_client):
    """Тест: show_user_profile создаёт UserSchema.fast_create() из данных API"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    user_data = {
        'id': 1,
        'registered_at': '2024-01-01T10:00:00',
        'sub_count': 3
    }
    
    fake_session = FakeAiohttpSession(json_data=user_data, status=200)
    conn = SubServiceConn(fake_session)
    mock_profile_kb.return_value = MagicMock()
    
    user = TgUser(id=888999, username='schema_test', first_name='Schema', last_name='Test', is_bot=False)
    message = Message(message_id=3, date=datetime.now(), chat=Chat(id=888999, type='private'), from_user=user)
    
    # Act
    with patch.object(UserSchema, 'fast_create', wraps=UserSchema.fast_create) as mock_fast_create:
        await show_user_profile(message, redis_client, conn)
        
        # Assert: проверяем что fast_create вызван с данными от API
        mock_fast_create.assert_called_once_with(user_data)


@pytest.mark.asyncio
@patch('bot.core.handlers.user_profile_handler.profile_kb')
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_show_user_profile_api_error(mock_answer, mock_profile_kb, redis_client):
    """Тест: show_user_profile обрабатывает ошибку API gracefully"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange: API возвращает ошибку
    fake_session = FakeAiohttpSession(raise_error=True)
    conn = SubServiceConn(fake_session)
    mock_profile_kb.return_value = MagicMock()
    
    user = TgUser(id=333444, username='error_user', first_name='Error', last_name='User', is_bot=False)
    message = Message(message_id=4, date=datetime.now(), chat=Chat(id=333444, type='private'), from_user=user)
    
    # Act - не должно выбросить исключение
    await show_user_profile(message, redis_client, conn)
    
    # Assert: проверяем что сообщение было отправлено (хоть и с ошибкой/пустыми данными)
    mock_answer.assert_called_once()
