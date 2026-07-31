"""
E2E тесты для callback_factory роутера (bot/core/handlers/callback_center.py).

Проверяет корректность маршрутизации callback'ов к соответствующим хэндлерам.
Использует реальные callback_data извлечённые из клавиатур для имитации нажатий пользователя.
"""

import pytest
import orjson
from unittest.mock import AsyncMock, patch, MagicMock
from aiogram.types import CallbackQuery, User as TgUser, Message, Chat
from datetime import datetime

from bot.core.handlers.callback_center import callback_factory
from bot.core.utils.keyboards import (
    shop_subs_slider, 
    user_subs_slider, 
    user_sub_plan_offers,
    subs_intro_kb
)
from bot.core.utils.anything import RedisKeys
from bot.config_dir.msg_templates import MessageTemplates


# ============================================================================
# Helper функции
# ============================================================================

def extract_callback_data(keyboard, button_index=None, button_text=None):
    """
    Извлекает callback_data из InlineKeyboard.
    
    Args:
        keyboard: InlineKeyboardMarkup объект
        button_index: кортеж (row, col) для извлечения по индексу
        button_text: текст кнопки для поиска (альтернатива индексу)
    
    Returns:
        callback_data: строка с callback_data или None
    """
    if button_text:
        for row in keyboard.inline_keyboard:
            for button in row:
                if button.text == button_text:
                    return button.callback_data
    
    if button_index:
        row, col = button_index
        return keyboard.inline_keyboard[row][col].callback_data
    
    return None


# ============================================================================
# Фикстуры
# ============================================================================

@pytest.fixture
def mock_template_render():
    """Мокаем MessageTemplates.render для упрощения тестов (обход frozen Pydantic)"""
    with patch.object(MessageTemplates, 'render', return_value="Mocked Offer Text") as mock:
        yield mock


@pytest.fixture
def sample_shop_plans_data():
    """Тестовые данные тарифных планов"""
    return [
        {
            'id': 1,
            'title': 'Basic Plan',
            'description': 'Basic plan',
            'sub_nodes_count': 3,
            'offer_prices': [
                {'offer_id': 1, 'cost': 49900, 'ttl_days': 30, 'traffic_day_limit': 10240, 
                 'traffic_limit': 307200, 'infinite_expire': False, 'infinite_traffic': False},
                {'offer_id': 2, 'cost': 129900, 'ttl_days': 90, 'traffic_day_limit': 10240,
                 'traffic_limit': 921600, 'infinite_expire': False, 'infinite_traffic': False}
            ]
        }
    ]


@pytest.fixture
def sample_user_subs_data():
    """Тестовые данные подписок пользователя"""
    return [
        {
            'user_sub_id': 1,
            'sub_plan_id': 1,
            'is_active': True,
            'is_limited': False,
            'expire_date': '2025-01-01T10:00:00.000000+00:00',
            'traffic_used_day_mb': 100,
            'infinite_traffic': False,
            'b64_id': 'test_b64_id',
            'infinite_expire': False,
            'traffic_limit_day': 10240,
            'used_mb': 5000,
            'used_mb_limit': 307200,
            'created_at': '2024-01-01T10:00:00.000000+00:00',
            'title': 'Basic Plan',
            'sub_nodes_count': 3,
            'offer_prices': [
                {'offer_id': 1, 'cost': 49900, 'ttl_days': 30, 'traffic_day_limit': 10240,
                 'traffic_limit': 307200, 'infinite_expire': False, 'infinite_traffic': False}
            ]
        }
    ]


# ============================================================================
# A. Общие callback'и - 2 теста
# ============================================================================

@pytest.mark.asyncio
@patch('bot.core.handlers.callback_center.start_handler', new_callable=AsyncMock)
@patch('bot.core.handlers.callback_center.bot.delete_message', new_callable=AsyncMock)
async def test_callback_back_deletes_message_and_calls_start(
    mock_delete,
    mock_start_handler,
    redis_client
):
    """Тест: callback 'back' удаляет сообщение и вызывает start_handler"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    fake_session = FakeAiohttpSession(json_data={}, status=200)
    conn = SubServiceConn(fake_session)
    state = AsyncMock()
    state.update_data = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    
    user = TgUser(id=123456, username='test_user', first_name='Test', last_name='User', is_bot=False)
    message = Message(message_id=100, date=datetime.now(), chat=Chat(id=123456, type='private'), from_user=user)
    
    with patch.object(CallbackQuery, 'answer', new_callable=AsyncMock):
        callback = CallbackQuery(id='cb_1', from_user=user, chat_instance='ci', message=message, data='back')
        
        # Act
        await callback_factory(callback, redis_client, state, conn)
        
        # Assert
        # 1. delete_message вызван
        mock_delete.assert_called_once_with(123456, 100)
        
        # 2. start_handler вызван с callback
        mock_start_handler.assert_called_once()
        call_args = mock_start_handler.call_args[0]
        assert call_args[0] == callback


@pytest.mark.asyncio
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_callback_answer_always_called(mock_answer, redis_client):
    """Тест: call.answer() вызывается в конце для любого callback"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    fake_session = FakeAiohttpSession(json_data={'sub_plans': []}, status=200)
    conn = SubServiceConn(fake_session)
    state = AsyncMock()
    state.update_data = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    
    user = TgUser(id=123456, username='test_user', first_name='Test', last_name='User', is_bot=False)
    message = Message(message_id=101, date=datetime.now(), chat=Chat(id=123456, type='private'), from_user=user)
    
    with patch.object(Message, 'answer', new_callable=AsyncMock):
        callback = CallbackQuery(id='cb_2', from_user=user, chat_instance='ci', message=message, data='subs-shop-intro')
        
        # Act
        await callback_factory(callback, redis_client, state, conn)
        
        # Assert: call.answer() вызван
        mock_answer.assert_called_once()


# ============================================================================
# B. ShopSubscriptions E2E - 4 теста
# ============================================================================

@pytest.mark.asyncio
async def test_shop_intro_callback_e2e(redis_client, mock_template_render, sample_shop_plans_data):
    """Тест E2E: callback 'subs-shop-intro' → shop_subscriptions_slider → сохранение в Redis"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    fake_session = FakeAiohttpSession(
        json_data={'sub_plans': sample_shop_plans_data},
        status=200
    )
    conn = SubServiceConn(fake_session)
    state = AsyncMock()
    state.update_data = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    
    user = TgUser(id=123456, username='shop_user', first_name='Shop', last_name='User', is_bot=False)
    message = Message(message_id=102, date=datetime.now(), chat=Chat(id=123456, type='private'), from_user=user)
    
    with patch.object(CallbackQuery, 'answer', new_callable=AsyncMock):
        with patch.object(Message, 'answer', new_callable=AsyncMock) as mock_message_answer:
            callback = CallbackQuery(id='cb_3', from_user=user, chat_instance='ci', message=message, data='subs-shop-intro')
            
            # Act
            await callback_factory(callback, redis_client, state, conn)
            
            # Assert
            # 1. API вызван
            assert len(fake_session.request_calls) == 1
            
            # 2. Данные сохранены в Redis
            stored_data = await redis_client.get(RedisKeys.shop_sub_plans)
            assert stored_data is not None
            
            # 3. Сообщение отправлено
            mock_message_answer.assert_called_once()


@pytest.mark.asyncio
async def test_shop_pagination_with_real_callback_data(redis_client, mock_template_render, sample_shop_plans_data):
    """Тест E2E: извлекаем реальный callback_data из клавиатуры '>' и эмулируем нажатие"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange: подготавливаем данные в Redis (добавляем второй план для пагинации)
    plans_data = sample_shop_plans_data * 2  # Дублируем данные
    plans_data[1]['id'] = 2
    plans_data[1]['title'] = 'Pro Plan'
    await redis_client.set(RedisKeys.shop_sub_plans, orjson.dumps(plans_data))
    
    fake_session = FakeAiohttpSession(json_data={}, status=200)
    conn = SubServiceConn(fake_session)
    state = AsyncMock()
    state.update_data = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    
    # Создаём клавиатуру и извлекаем callback_data кнопки ">"
    kb = shop_subs_slider(0, 2, sample_shop_plans_data[0]['offer_prices'])
    next_callback = extract_callback_data(kb, button_text='>')
    
    # Проверяем что callback_data извлечён корректно
    assert next_callback is not None
    assert 'subs-shop-pagen' in next_callback
    
    user = TgUser(id=234567, username='paginate_user', first_name='Pag', last_name='User', is_bot=False)
    message = Message(message_id=103, date=datetime.now(), chat=Chat(id=234567, type='private'), from_user=user)
    
    with patch.object(CallbackQuery, 'answer', new_callable=AsyncMock):
        with patch.object(Message, 'edit_text', new_callable=AsyncMock) as mock_edit:
            callback = CallbackQuery(id='cb_4', from_user=user, chat_instance='ci', message=message, data=next_callback)
            
            # Act: эмулируем нажатие на кнопку ">"
            await callback_factory(callback, redis_client, state, conn)
            
            # Assert: edit_text вызван
            mock_edit.assert_called_once()


@pytest.mark.asyncio
async def test_shop_offer_selection_with_real_callback_data(redis_client, mock_template_render, sample_shop_plans_data):
    """Тест E2E: извлекаем callback_data оффера и эмулируем выбор пользователя"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    await redis_client.set(RedisKeys.shop_sub_plans, orjson.dumps(sample_shop_plans_data))
    
    fake_session = FakeAiohttpSession(
        json_data={'payment_url': 'https://payment.example.com/pay/test'},
        status=200
    )
    conn = SubServiceConn(fake_session)
    state = AsyncMock()
    state.update_data = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    
    # Создаём клавиатуру и извлекаем callback_data первого оффера
    kb = shop_subs_slider(0, 1, sample_shop_plans_data[0]['offer_prices'])
    # Офферы начинаются с 4-й кнопки (3 кнопки навигации + офферы)
    offer_callback = extract_callback_data(kb, button_index=(1, 0))
    
    # Проверяем формат callback_data
    assert offer_callback is not None
    assert 'subs-shop-offer' in offer_callback
    
    user = TgUser(id=345678, username='offer_user', first_name='Offer', last_name='User', is_bot=False)
    message = Message(message_id=104, date=datetime.now(), chat=Chat(id=345678, type='private'), from_user=user)
    
    with patch.object(CallbackQuery, 'answer', new_callable=AsyncMock):
        with patch.object(Message, 'edit_text', new_callable=AsyncMock) as mock_edit:
            callback = CallbackQuery(id='cb_5', from_user=user, chat_instance='ci', message=message, data=offer_callback)
            
            # Act: эмулируем выбор оффера
            await callback_factory(callback, redis_client, state, conn)
            
            # Assert
            # 1. API вызван для получения payment_url
            assert len(fake_session.request_calls) == 1
            
            # 2. edit_text вызван с платёжной информацией
            mock_edit.assert_called_once()


@pytest.mark.asyncio
async def test_shop_fallback_when_cache_empty(redis_client, mock_template_render):
    """Тест: когда данные пропали из Redis, edit_text НЕ вызывается"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange: Redis пустой
    await redis_client.delete(RedisKeys.shop_sub_plans)
    
    fake_session = FakeAiohttpSession(json_data={}, status=200)
    conn = SubServiceConn(fake_session)
    state = AsyncMock()
    state.update_data = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    
    user = TgUser(id=456789, username='empty_cache', first_name='Empty', last_name='Cache', is_bot=False)
    message = Message(message_id=105, date=datetime.now(), chat=Chat(id=456789, type='private'), from_user=user)
    
    with patch.object(CallbackQuery, 'answer', new_callable=AsyncMock):
        with patch.object(Message, 'edit_text', new_callable=AsyncMock) as mock_edit:
            callback = CallbackQuery(id='cb_6', from_user=user, chat_instance='ci', message=message, data='subs-shop-pagen_1')
            
            # Act
            await callback_factory(callback, redis_client, state, conn)
            
            # Assert: edit_text НЕ вызван (нет данных)
            mock_edit.assert_not_called()


# ============================================================================
# C. UserSubscriptions E2E - 5 тестов
# ============================================================================

@pytest.mark.asyncio
async def test_user_subs_intro_callback_e2e(redis_client, mock_template_render, sample_user_subs_data):
    """Тест E2E: callback 'subs-upd-intro' → user_subscriptions_slider → сохранение в FSMContext"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    fake_session = FakeAiohttpSession(
        json_data={'user_subs': sample_user_subs_data},
        status=200
    )
    conn = SubServiceConn(fake_session)
    state = AsyncMock()
    state.update_data = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    
    user = TgUser(id=567890, username='user_subs', first_name='UserSubs', last_name='User', is_bot=False)
    message = Message(message_id=106, date=datetime.now(), chat=Chat(id=567890, type='private'), from_user=user)
    
    with patch.object(CallbackQuery, 'answer', new_callable=AsyncMock):
        with patch.object(Message, 'answer', new_callable=AsyncMock) as mock_message_answer:
            callback = CallbackQuery(id='cb_7', from_user=user, chat_instance='ci', message=message, data='subs-upd-intro')
            
            # Act
            await callback_factory(callback, redis_client, state, conn)
            
            # Assert
            # 1. API вызван
            assert len(fake_session.request_calls) == 1
            
            # 2. FSMContext.update_data вызван
            state.update_data.assert_called_once_with(user_subs=sample_user_subs_data)
            
            # 3. Сообщение отправлено
            mock_message_answer.assert_called_once()


@pytest.mark.asyncio
async def test_user_subs_pagination_with_real_callback_data(redis_client, mock_template_render, sample_user_subs_data):
    """Тест E2E: извлекаем реальный callback_data из user_subs_slider и эмулируем навигацию"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange: добавляем вторую подписку для пагинации
    user_subs_data = sample_user_subs_data * 2
    user_subs_data[1]['user_sub_id'] = 2
    user_subs_data[1]['title'] = 'Premium Plan'
    
    fake_session = FakeAiohttpSession(json_data={}, status=200)
    conn = SubServiceConn(fake_session)
    state = AsyncMock()
    state.update_data = AsyncMock()
    state.get_data = AsyncMock(return_value={'user_subs': user_subs_data})
    
    # Создаём клавиатуру и извлекаем callback_data кнопки ">"
    kb = user_subs_slider(0, 2)
    next_callback = extract_callback_data(kb, button_text='>')
    
    # Проверяем формат
    assert next_callback is not None
    assert 'subs-user-pagen' in next_callback
    
    user = TgUser(id=678901, username='user_pag', first_name='UserPag', last_name='User', is_bot=False)
    message = Message(message_id=107, date=datetime.now(), chat=Chat(id=678901, type='private'), from_user=user)
    
    with patch.object(CallbackQuery, 'answer', new_callable=AsyncMock):
        with patch.object(Message, 'edit_text', new_callable=AsyncMock) as mock_edit:
            callback = CallbackQuery(id='cb_8', from_user=user, chat_instance='ci', message=message, data=next_callback)
            
            # Act: эмулируем нажатие ">"
            await callback_factory(callback, redis_client, state, conn)
            
            # Assert: edit_text вызван
            mock_edit.assert_called_once()


@pytest.mark.asyncio
async def test_user_subs_extend_button_with_real_callback_data(redis_client, mock_template_render, sample_user_subs_data):
    """Тест E2E: извлекаем callback_data кнопки '🔄 Продлить' и эмулируем нажатие"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    fake_session = FakeAiohttpSession(json_data={}, status=200)
    conn = SubServiceConn(fake_session)
    state = AsyncMock()
    state.update_data = AsyncMock()
    state.get_data = AsyncMock(return_value={'user_subs': sample_user_subs_data})
    
    # Создаём клавиатуру и извлекаем callback_data кнопки "🔄 Продлить"
    kb = user_subs_slider(0, 2)
    extend_callback = extract_callback_data(kb, button_text='🔄 Продлить')
    
    # Проверяем формат
    assert extend_callback is not None
    assert 'subs-user-upd' in extend_callback
    
    user = TgUser(id=789012, username='extend_user', first_name='Extend', last_name='User', is_bot=False)
    message = Message(message_id=108, date=datetime.now(), chat=Chat(id=789012, type='private'), from_user=user)
    
    with patch.object(CallbackQuery, 'answer', new_callable=AsyncMock):
        with patch.object(Message, 'edit_text', new_callable=AsyncMock) as mock_edit:
            callback = CallbackQuery(id='cb_9', from_user=user, chat_instance='ci', message=message, data=extend_callback)
            
            # Act: эмулируем нажатие "🔄 Продлить"
            await callback_factory(callback, redis_client, state, conn)
            
            # Assert: edit_text вызван с офферами
            mock_edit.assert_called_once()


@pytest.mark.asyncio
async def test_user_subs_offer_selection_with_real_callback_data(redis_client, mock_template_render, sample_user_subs_data):
    """Тест E2E: извлекаем callback_data оффера из user_sub_plan_offers и эмулируем выбор"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    fake_session = FakeAiohttpSession(
        json_data={'payment_url': 'https://payment.example.com/pay/user_test'},
        status=200
    )
    conn = SubServiceConn(fake_session)
    state = AsyncMock()
    state.update_data = AsyncMock()
    state.get_data = AsyncMock(return_value={'user_subs': sample_user_subs_data})
    
    # Создаём клавиатуру офферов и извлекаем callback_data первого оффера
    kb = user_sub_plan_offers(0, sample_user_subs_data[0]['offer_prices'])
    offer_callback = extract_callback_data(kb, button_index=(0, 0))
    
    # Проверяем формат
    assert offer_callback is not None
    assert 'subs-user-offer' in offer_callback
    
    user = TgUser(id=890123, username='user_offer', first_name='UserOffer', last_name='User', is_bot=False)
    message = Message(message_id=109, date=datetime.now(), chat=Chat(id=890123, type='private'), from_user=user)
    
    with patch.object(CallbackQuery, 'answer', new_callable=AsyncMock):
        with patch.object(Message, 'edit_text', new_callable=AsyncMock) as mock_edit:
            callback = CallbackQuery(id='cb_10', from_user=user, chat_instance='ci', message=message, data=offer_callback)
            
            # Act: эмулируем выбор оффера
            await callback_factory(callback, redis_client, state, conn)
            
            # Assert
            # 1. API вызван
            assert len(fake_session.request_calls) == 1
            
            # 2. edit_text вызван с платёжной информацией
            mock_edit.assert_called_once()


@pytest.mark.asyncio
async def test_user_subs_fallback_when_state_empty(redis_client, mock_template_render):
    """Тест: когда данные пропали из FSMContext, edit_text НЕ вызывается"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange: FSMContext пустой
    fake_session = FakeAiohttpSession(json_data={}, status=200)
    conn = SubServiceConn(fake_session)
    state = AsyncMock()
    state.update_data = AsyncMock()
    state.get_data = AsyncMock(return_value={})  # Нет user_subs
    
    user = TgUser(id=901234, username='empty_state', first_name='Empty', last_name='State', is_bot=False)
    message = Message(message_id=110, date=datetime.now(), chat=Chat(id=901234, type='private'), from_user=user)
    
    with patch.object(CallbackQuery, 'answer', new_callable=AsyncMock):
        with patch.object(Message, 'edit_text', new_callable=AsyncMock) as mock_edit:
            callback = CallbackQuery(id='cb_11', from_user=user, chat_instance='ci', message=message, data='subs-user-pagen_1')
            
            # Act
            await callback_factory(callback, redis_client, state, conn)
            
            # Assert: edit_text НЕ вызван (нет данных)
            mock_edit.assert_not_called()


# ============================================================================
# D. Дополнительные E2E тесты - 2 теста
# ============================================================================

@pytest.mark.asyncio
async def test_callback_data_parsing_shop_offer(redis_client, mock_template_render, sample_shop_plans_data):
    """Тест: корректный парсинг индексов из callback_data 'subs-shop-offer_1_2'"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange: подготавливаем 2 плана с несколькими офферами
    plans_data = sample_shop_plans_data * 2  # Копируем для теста
    plans_data[1]['id'] = 2
    await redis_client.set(RedisKeys.shop_sub_plans, orjson.dumps(plans_data))
    
    fake_session = FakeAiohttpSession(
        json_data={'payment_url': 'https://payment.example.com'},
        status=200
    )
    conn = SubServiceConn(fake_session)
    state = AsyncMock()
    state.update_data = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    
    user = TgUser(id=111222, username='parse_test', first_name='Parse', last_name='Test', is_bot=False)
    message = Message(message_id=111, date=datetime.now(), chat=Chat(id=111222, type='private'), from_user=user)
    
    with patch.object(CallbackQuery, 'answer', new_callable=AsyncMock):
        with patch.object(Message, 'edit_text', new_callable=AsyncMock):
            # Тестируем парсинг: sub_plan_idx=1, offer_idx=1
            callback = CallbackQuery(id='cb_12', from_user=user, chat_instance='ci', message=message, data='subs-shop-offer_1_1')
            
            # Act
            await callback_factory(callback, redis_client, state, conn)
            
            # Assert: проверяем что правильные индексы переданы в API
            call = fake_session.request_calls[0]
            json_payload = call['kwargs']['json']
            # План с индексом 1 имеет id=2
            assert json_payload['sub_plan_id'] == 2
            # Оффер с индексом 1 (второй оффер из списка)
            assert json_payload['offer_id'] == plans_data[1]['offer_prices'][1]['offer_id']


@pytest.mark.asyncio
async def test_callback_intro_keyboard_integration(redis_client):
    """Тест E2E: проверяем интеграцию с subs_intro_kb клавиатурой"""
    # Arrange: создаём клавиатуру intro
    kb = subs_intro_kb()
    
    # Извлекаем все callback_data
    extend_cb = extract_callback_data(kb, button_text='🔄 Продлить')
    buy_cb = extract_callback_data(kb, button_text='➕ Купить новую')
    back_cb = extract_callback_data(kb, button_text='⬅️ Назад')
    
    # Assert: проверяем что callback_data соответствуют ожиданиям
    assert extend_cb == 'subs-upd-intro'
    assert buy_cb == 'subs-shop-intro'
    assert back_cb == 'back'
