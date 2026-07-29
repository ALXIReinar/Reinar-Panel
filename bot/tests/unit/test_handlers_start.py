"""
Тесты для хэндлеров start.py (bot/core/handlers/start.py).

Проверяет корректность работы:
- start_handler() - регистрация пользователя, рендеринг шаблона, отправка сообщения
- helping() - отправка справочного сообщения
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from aiogram.types import Message, CallbackQuery, User as TgUser, Chat
from datetime import datetime

from bot.core.handlers.start import start_handler, helping
from bot.core.utils.schemas import UserSchema


# ============================================================================
# A. start_handler() - 9 тестов
# ============================================================================

# A.1. Успешные сценарии - 4 теста

@pytest.mark.asyncio
@patch('bot.core.handlers.start.set_commands')
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_start_handler_message_success(mock_answer, mock_set_commands, redis_client):
    """Тест: start_handler с Message успешно регистрирует пользователя и отправляет приветствие"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    fake_session = FakeAiohttpSession(
        json_data={
            'insert_success': True,
            'sub_count': 0,
            'user_id': 1,
            'registered_at': '2024-01-01T10:00:00'
        }
    )
    
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=123456, username='test_user', first_name='Test', last_name='User', is_bot=False)
    message = Message(message_id=1, date=datetime.now(), chat=Chat(id=123456, type='private'), from_user=user)
    
    # Act
    await start_handler(message, redis_client, conn)
    
    # Assert
    # 1. Проверяем что вызван save_user
    assert len(fake_session.request_calls) == 1
    call = fake_session.request_calls[0]
    assert call['kwargs']['json']['tg_id'] == 123456
    assert call['kwargs']['json']['return_data'] is True
    
    # 2. Проверяем что отправлено сообщение
    mock_answer.assert_called_once()
    call_args = mock_answer.call_args
    assert 'reply_markup' in call_args[1]  # Клавиатура передана
    
    # 3. Проверяем что вызван set_commands
    mock_set_commands.assert_called_once()


@pytest.mark.asyncio
@patch('bot.core.handlers.start.set_commands')
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_start_handler_callback_success(mock_callback_answer, mock_set_commands, redis_client):
    """Тест: start_handler с CallbackQuery успешно обрабатывается"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    fake_session = FakeAiohttpSession(
        json_data={
            'insert_success': False,
            'id': 1,
            'sub_count': 2,
            'registered_at': '2023-12-01T10:00:00',
            'user_id': 1
        }
    )
    
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=654321, username='callback_user', first_name='CB', last_name='User', is_bot=False)
    message = Message(message_id=2, date=datetime.now(), chat=Chat(id=654321, type='private'), from_user=user)
    
    # Патчим message.answer для callback
    with patch.object(Message, 'answer', new_callable=AsyncMock) as mock_message_answer:
        callback = CallbackQuery(id='cb_1', from_user=user, chat_instance='ci', message=message, data='start')
        
        # Act
        await start_handler(callback, redis_client, conn)
        
        # Assert
        # Для CallbackQuery используется callback.message.answer()
        mock_message_answer.assert_called_once()
        call_args = mock_message_answer.call_args
        assert 'reply_markup' in call_args[1]


@pytest.mark.asyncio
@patch('bot.core.handlers.start.set_commands')
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_start_handler_saves_user_to_api(mock_answer, mock_set_commands, redis_client):
    """Тест: start_handler вызывает save_user() с правильными параметрами"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    fake_session = FakeAiohttpSession(
        json_data={'insert_success': True, 'sub_count': 0, 'user_id': 1}
    )
    
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=999888, username='api_test', first_name='API', last_name='Test', is_bot=False)
    message = Message(message_id=3, date=datetime.now(), chat=Chat(id=999888, type='private'), from_user=user)
    
    # Act
    await start_handler(message, redis_client, conn)
    
    # Assert: проверяем параметры вызова save_user
    call = fake_session.request_calls[0]
    json_payload = call['kwargs']['json']
    
    assert json_payload['tg_id'] == 999888
    assert json_payload['tg_username'] == 'api_test'
    assert json_payload['return_data'] is True


@pytest.mark.asyncio
@patch('bot.core.handlers.start.set_commands')
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_start_handler_sets_commands(mock_answer, mock_set_commands, redis_client):
    """Тест: start_handler вызывает set_commands(bot)"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    from bot.config_dir.config import bot
    
    # Arrange
    fake_session = FakeAiohttpSession(
        json_data={'insert_success': True, 'sub_count': 0, 'user_id': 1}
    )
    
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=111222, username='cmd_test', first_name='Cmd', last_name='Test', is_bot=False)
    message = Message(message_id=4, date=datetime.now(), chat=Chat(id=111222, type='private'), from_user=user)
    
    # Act
    await start_handler(message, redis_client, conn)
    
    # Assert
    mock_set_commands.assert_called_once_with(bot)


# A.2. Обработка ошибок API - 2 теста

@pytest.mark.asyncio
@patch('bot.core.handlers.start.set_commands')
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_start_handler_api_error(mock_answer, mock_set_commands, redis_client):
    """Тест: start_handler обрабатывает ошибку API (ok=False) и показывает сообщение об ошибке"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange: API возвращает ошибку
    fake_session = FakeAiohttpSession(raise_error=True)
    
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=333444, username='error_user', first_name='Error', last_name='User', is_bot=False)
    message = Message(message_id=5, date=datetime.now(), chat=Chat(id=333444, type='private'), from_user=user)
    
    # Act
    await start_handler(message, redis_client, conn)
    
    # Assert: проверяем что отправлено сообщение об ошибке
    mock_answer.assert_called_once()
    call_args = mock_answer.call_args[0][0]
    assert 'Что-то пошло не так' in call_args or 'не так' in call_args


@pytest.mark.asyncio
@patch('bot.core.handlers.start.set_commands')
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_start_handler_api_exception(mock_answer, mock_set_commands, redis_client):
    """Тест: start_handler обрабатывает исключение от API gracefully"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange: имитация сетевой ошибки
    fake_session = FakeAiohttpSession(raise_error=True)
    
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=555666, username='exception_user', first_name='Exception', last_name='User', is_bot=False)
    message = Message(message_id=6, date=datetime.now(), chat=Chat(id=555666, type='private'), from_user=user)
    
    # Act - не должно выбросить исключение
    await start_handler(message, redis_client, conn)
    
    # Assert: проверяем что отправлено сообщение (хоть и об ошибке)
    mock_answer.assert_called_once()


# A.3. Клавиатура и схемы - 2 теста

@pytest.mark.asyncio
@patch('bot.core.handlers.start.set_commands')
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_start_handler_user_schema_creation(mock_answer, mock_set_commands, redis_client):
    """Тест: start_handler создаёт UserSchema.fast_create() из данных API"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    user_data = {
        'insert_success': True,
        'sub_count': 0,
        'user_id': 1,
        'registered_at': '2024-01-01T10:00:00'
    }
    
    fake_session = FakeAiohttpSession(json_data=user_data)
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=888999, username='schema_test', first_name='Schema', last_name='Test', is_bot=False)
    message = Message(message_id=8, date=datetime.now(), chat=Chat(id=888999, type='private'), from_user=user)
    
    # Act
    with patch.object(UserSchema, 'fast_create', wraps=UserSchema.fast_create) as mock_fast_create:
        await start_handler(message, redis_client, conn)
        
        # Assert: проверяем что fast_create вызван с данными от API
        mock_fast_create.assert_called_once_with(user_data)


# A.4. Клавиатура - 1 тест

@pytest.mark.asyncio
@patch('bot.core.handlers.start.set_commands')
@patch('bot.core.handlers.start.main_kb')
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_start_handler_sends_main_keyboard(mock_answer, mock_main_kb, mock_set_commands, redis_client):
    """Тест: start_handler отправляет клавиатуру main_kb()"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    fake_session = FakeAiohttpSession(
        json_data={'insert_success': True, 'sub_count': 0, 'user_id': 1}
    )
    
    conn = SubServiceConn(fake_session)
    mock_keyboard = MagicMock()
    mock_main_kb.return_value = mock_keyboard
    
    user = TgUser(id=101010, username='kb_test', first_name='KB', last_name='Test', is_bot=False)
    message = Message(message_id=9, date=datetime.now(), chat=Chat(id=101010, type='private'), from_user=user)
    
    # Act
    await start_handler(message, redis_client, conn)
    
    # Assert
    mock_main_kb.assert_called_once()
    mock_answer.assert_called_once()
    
    # Проверяем что клавиатура передана в answer
    call_kwargs = mock_answer.call_args[1]
    assert call_kwargs['reply_markup'] == mock_keyboard


# ============================================================================
# B. helping() - 1 тест
# ============================================================================

@pytest.mark.asyncio
@patch.object(Message, 'answer', new_callable=AsyncMock)
async def test_helping_sends_message(mock_answer):
    """Тест: helping() отправляет сообщение пользователю (рендеринг протестирован в test_placeholders.py)"""
    # Arrange
    user = TgUser(id=303030, username='help_user', first_name='Help', last_name='User', is_bot=False)
    message = Message(message_id=11, date=datetime.now(), chat=Chat(id=303030, type='private'), from_user=user)
    
    # Act
    await helping(message)
    
    # Assert: проверяем что сообщение было отправлено
    mock_answer.assert_called_once()
    # Проверяем что отправлен какой-то текст (не пустая строка)
    call_args = mock_answer.call_args[0][0]
    assert isinstance(call_args, str)
    assert len(call_args) > 0
