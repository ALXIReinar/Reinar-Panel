"""
Тесты для хэндлеров UserSubscriptions класса (bot/core/handlers/subscriptions_shop.py).

Проверяет корректность работы:
- user_subscriptions_slider() - получение подписок пользователя, сохранение в FSMContext
- build_user_subs_slider_msg() - построение сообщения слайдера из FSMContext
- show_price_offers() - отображение ценовых предложений
- give_issued_payment() - формирование ссылки на оплату
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from aiogram.types import CallbackQuery, User as TgUser, Message, Chat
from datetime import datetime

from bot.core.handlers.subscriptions_shop import UserSubscriptions
from bot.core.utils.schemas import UserSubSchema


# ============================================================================
# Фикстуры
# ============================================================================

@pytest.fixture
def mock_fsm_context():
    """
    Mock для FSMContext с методами update_data() и get_data().
    По умолчанию get_data() возвращает пустой dict (можно переопределить в тестах).
    """
    context = AsyncMock()
    context.update_data = AsyncMock()
    context.get_data = AsyncMock(return_value={})
    return context


@pytest.fixture
def sample_user_subs_data():
    """Пример данных подписок пользователя (список из 2 подписок)"""
    return [
        {
            'user_sub_id': 1,
            'sub_plan_id': 1,
            'is_active': True,
            'is_limited': False,
            'expire_date': '2025-01-01T10:00:00.000000+00:00',
            'traffic_used_day_mb': 100,
            'infinite_traffic': False,
            'b64_id': 'test_b64_id_1',
            'infinite_expire': False,
            'traffic_limit_day': 10240,
            'used_mb': 5000,
            'used_mb_limit': 307200,
            'created_at': '2024-01-01T10:00:00.000000+00:00',
            'title': 'Basic Plan',
            'sub_nodes_count': 3,  # Добавлено обязательное поле
            'offer_prices': [
                {
                    'offer_id': 1,
                    'cost': 49900,
                    'ttl_days': 30,
                    'traffic_day_limit': 10240,
                    'traffic_limit': 307200,
                    'infinite_expire': False,
                    'infinite_traffic': False
                }
            ]
        },
        {
            'user_sub_id': 2,
            'sub_plan_id': 2,
            'is_active': True,
            'is_limited': False,
            'expire_date': '2025-06-01T10:00:00.000000+00:00',
            'traffic_used_day_mb': 200,
            'infinite_traffic': True,
            'b64_id': 'test_b64_id_2',
            'infinite_expire': False,
            'traffic_limit_day': 20480,
            'used_mb': 10000,
            'used_mb_limit': 614400,
            'created_at': '2024-02-01T10:00:00.000000+00:00',
            'title': 'Premium Plan',
            'sub_nodes_count': 5,  # Добавлено обязательное поле
            'offer_prices': [
                {
                    'offer_id': 2,
                    'cost': 99900,
                    'ttl_days': 30,
                    'traffic_day_limit': 20480,
                    'traffic_limit': 614400,
                    'infinite_expire': False,
                    'infinite_traffic': True
                }
            ]
        }
    ]


# ============================================================================
# A. user_subscriptions_slider() - 5 тестов
# ============================================================================

@pytest.mark.asyncio
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
@patch('bot.core.handlers.subscriptions_shop.UserSubscriptions.build_user_subs_slider_msg', new_callable=AsyncMock)
async def test_user_subscriptions_slider_success(
    mock_build,
    mock_callback_answer,
    redis_client,
    mock_fsm_context,
    sample_user_subs_data
):
    """Тест: user_subscriptions_slider успешно получает подписки, сохраняет в state и отображает слайдер"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    fake_session = FakeAiohttpSession(
        json_data={'user_subs': sample_user_subs_data},
        status=200
    )
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=123456, username='test_user', first_name='Test', last_name='User', is_bot=False)
    message = Message(message_id=1, date=datetime.now(), chat=Chat(id=123456, type='private'), from_user=user)
    
    # Mock build возвращает текст и клавиатуру
    mock_build.return_value = ('Слайдер текст', MagicMock())
    
    # Патчим message.answer
    with patch.object(Message, 'answer', new_callable=AsyncMock) as mock_message_answer:
        callback = CallbackQuery(id='cb_1', from_user=user, chat_instance='ci', message=message, data='subs-upd-intro')
        
        # Act
        await UserSubscriptions.user_subscriptions_slider(callback, redis_client, mock_fsm_context, conn)
        
        # Assert
        # 1. API вызван
        assert len(fake_session.request_calls) == 1
        
        # 2. state.update_data вызван с подписками
        mock_fsm_context.update_data.assert_called_once_with(user_subs=sample_user_subs_data)
        
        # 3. build_user_subs_slider_msg вызван
        mock_build.assert_called_once()
        
        # 4. Сообщение отправлено
        mock_message_answer.assert_called_once()


@pytest.mark.asyncio
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_user_subscriptions_slider_calls_api_with_tg_id(
    mock_callback_answer,
    redis_client,
    mock_fsm_context,
    sample_user_subs_data
):
    """Тест: user_subscriptions_slider вызывает API с правильным tg_id"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    from bot.core.utils.anything import SubServiceUris
    
    # Arrange
    fake_session = FakeAiohttpSession(
        json_data={'user_subs': sample_user_subs_data},
        status=200
    )
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=999888, username='api_test', first_name='API', last_name='Test', is_bot=False)
    message = Message(message_id=2, date=datetime.now(), chat=Chat(id=999888, type='private'), from_user=user)
    
    with patch.object(Message, 'answer', new_callable=AsyncMock):
        with patch('bot.core.handlers.subscriptions_shop.UserSubscriptions.build_user_subs_slider_msg', new_callable=AsyncMock) as mock_build:
            mock_build.return_value = ('Text', MagicMock())
            
            callback = CallbackQuery(id='cb_2', from_user=user, chat_instance='ci', message=message, data='subs-upd-intro')
            
            # Act
            await UserSubscriptions.user_subscriptions_slider(callback, redis_client, mock_fsm_context, conn)
            
            # Assert: проверяем параметры API запроса
            call = fake_session.request_calls[0]
            assert call['method'] == 'GET'
            assert SubServiceUris.get_user_subs_all in call['url']
            assert call['kwargs']['params']['tg_id'] == 999888


@pytest.mark.asyncio
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_user_subscriptions_slider_saves_to_fsm_context(
    mock_callback_answer,
    redis_client,
    mock_fsm_context,
    sample_user_subs_data
):
    """Тест: user_subscriptions_slider сохраняет подписки в FSMContext через update_data()"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    fake_session = FakeAiohttpSession(
        json_data={'user_subs': sample_user_subs_data},
        status=200
    )
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=111222, username='fsm_test', first_name='FSM', last_name='Test', is_bot=False)
    message = Message(message_id=3, date=datetime.now(), chat=Chat(id=111222, type='private'), from_user=user)
    
    with patch.object(Message, 'answer', new_callable=AsyncMock):
        with patch('bot.core.handlers.subscriptions_shop.UserSubscriptions.build_user_subs_slider_msg', new_callable=AsyncMock) as mock_build:
            mock_build.return_value = ('Text', MagicMock())
            
            callback = CallbackQuery(id='cb_3', from_user=user, chat_instance='ci', message=message, data='subs-upd-intro')
            
            # Act
            await UserSubscriptions.user_subscriptions_slider(callback, redis_client, mock_fsm_context, conn)
            
            # Assert: проверяем что update_data вызван с правильными данными
            mock_fsm_context.update_data.assert_called_once_with(user_subs=sample_user_subs_data)


@pytest.mark.asyncio
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
@patch('bot.core.handlers.subscriptions_shop.fallback_user_subs')
async def test_user_subscriptions_slider_fallback_no_subs(
    mock_fallback_kb,
    mock_callback_answer,
    redis_client,
    mock_fsm_context
):
    """Тест: user_subscriptions_slider показывает fallback когда у пользователя нет подписок"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange: API возвращает пустой список подписок
    fake_session = FakeAiohttpSession(
        json_data={'user_subs': []},
        status=200
    )
    conn = SubServiceConn(fake_session)
    mock_fallback_kb.return_value = MagicMock()
    
    user = TgUser(id=333444, username='no_subs', first_name='No', last_name='Subs', is_bot=False)
    message = Message(message_id=4, date=datetime.now(), chat=Chat(id=333444, type='private'), from_user=user)
    
    with patch.object(Message, 'answer', new_callable=AsyncMock) as mock_message_answer:
        callback = CallbackQuery(id='cb_4', from_user=user, chat_instance='ci', message=message, data='subs-upd-intro')
        
        # Act
        await UserSubscriptions.user_subscriptions_slider(callback, redis_client, mock_fsm_context, conn)
        
        # Assert
        # 1. fallback_user_subs() вызван
        mock_fallback_kb.assert_called_once()
        
        # 2. Сообщение отправлено с fallback клавиатурой
        mock_message_answer.assert_called_once()
        call_args = mock_message_answer.call_args[0][0]
        assert 'нет ни одной подписки' in call_args.lower()
        
        # 3. update_data НЕ вызван (нечего сохранять)
        mock_fsm_context.update_data.assert_not_called()


@pytest.mark.asyncio
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_user_subscriptions_slider_calls_build_with_zero_index(
    mock_callback_answer,
    redis_client,
    mock_fsm_context,
    sample_user_subs_data
):
    """Тест: user_subscriptions_slider вызывает build_user_subs_slider_msg с индексом 0"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    fake_session = FakeAiohttpSession(
        json_data={'user_subs': sample_user_subs_data},
        status=200
    )
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=555666, username='build_test', first_name='Build', last_name='Test', is_bot=False)
    message = Message(message_id=5, date=datetime.now(), chat=Chat(id=555666, type='private'), from_user=user)
    
    with patch.object(Message, 'answer', new_callable=AsyncMock):
        with patch('bot.core.handlers.subscriptions_shop.UserSubscriptions.build_user_subs_slider_msg', new_callable=AsyncMock) as mock_build:
            mock_build.return_value = ('Text', MagicMock())
            
            callback = CallbackQuery(id='cb_5', from_user=user, chat_instance='ci', message=message, data='subs-upd-intro')
            
            # Act
            await UserSubscriptions.user_subscriptions_slider(callback, redis_client, mock_fsm_context, conn)
            
            # Assert: build вызван с slider_idx=0
            assert mock_build.call_count == 1
            call_args = mock_build.call_args[0]
            assert call_args[0] == 0  # Первый аргумент - slider_idx


# ============================================================================
# B. build_user_subs_slider_msg() - 5 тестов
# ============================================================================

@pytest.mark.asyncio
async def test_build_user_subs_slider_msg_success(mock_fsm_context, sample_user_subs_data):
    """Тест: build_user_subs_slider_msg успешно возвращает текст и клавиатуру"""
    # Arrange
    mock_fsm_context.get_data = AsyncMock(return_value={'user_subs': sample_user_subs_data})
    
    user = TgUser(id=123456, username='test_user', first_name='Test', last_name='User', is_bot=False)
    message = Message(message_id=6, date=datetime.now(), chat=Chat(id=123456, type='private'), from_user=user)
    callback = CallbackQuery(id='cb_6', from_user=user, chat_instance='ci', message=message, data='subs-user-pagen_0')
    
    # Act
    text, kb = await UserSubscriptions.build_user_subs_slider_msg(0, callback, mock_fsm_context)
    
    # Assert
    assert text is not None
    assert kb is not None
    assert isinstance(text, str)
    assert len(text) > 0


@pytest.mark.asyncio
async def test_build_user_subs_slider_msg_calls_get_data(mock_fsm_context, sample_user_subs_data):
    """Тест: build_user_subs_slider_msg вызывает state.get_data() для получения подписок"""
    # Arrange
    mock_fsm_context.get_data = AsyncMock(return_value={'user_subs': sample_user_subs_data})
    
    user = TgUser(id=789012, username='get_data_test', first_name='GetData', last_name='Test', is_bot=False)
    message = Message(message_id=7, date=datetime.now(), chat=Chat(id=789012, type='private'), from_user=user)
    callback = CallbackQuery(id='cb_7', from_user=user, chat_instance='ci', message=message, data='subs-user-pagen_0')
    
    # Act
    await UserSubscriptions.build_user_subs_slider_msg(0, callback, mock_fsm_context)
    
    # Assert: get_data вызван
    mock_fsm_context.get_data.assert_called_once()


@pytest.mark.asyncio
async def test_build_user_subs_slider_msg_fallback_no_state(mock_fsm_context):
    """Тест: build_user_subs_slider_msg возвращает (None, None) когда user_subs отсутствуют в state"""
    # Arrange: get_data возвращает пустой dict (нет user_subs)
    mock_fsm_context.get_data = AsyncMock(return_value={})
    
    user = TgUser(id=345678, username='no_state', first_name='No', last_name='State', is_bot=False)
    message = Message(message_id=8, date=datetime.now(), chat=Chat(id=345678, type='private'), from_user=user)
    callback = CallbackQuery(id='cb_8', from_user=user, chat_instance='ci', message=message, data='subs-user-pagen_0')
    
    # Act
    text, kb = await UserSubscriptions.build_user_subs_slider_msg(0, callback, mock_fsm_context)
    
    # Assert: возвращает (None, None)
    assert text is None
    assert kb is None


@pytest.mark.asyncio
async def test_build_user_subs_slider_msg_invalid_index_negative(mock_fsm_context, sample_user_subs_data):
    """Тест: build_user_subs_slider_msg выбрасывает IndexError при slider_idx=-1"""
    # Arrange
    mock_fsm_context.get_data = AsyncMock(return_value={'user_subs': sample_user_subs_data})
    
    user = TgUser(id=901234, username='neg_idx', first_name='Negative', last_name='Index', is_bot=False)
    message = Message(message_id=9, date=datetime.now(), chat=Chat(id=901234, type='private'), from_user=user)
    callback = CallbackQuery(id='cb_9', from_user=user, chat_instance='ci', message=message, data='subs-user-pagen_-1')
    
    # Act & Assert: ожидаем IndexError
    # Примечание: Python поддерживает отрицательные индексы, но -1 обращается к последнему элементу
    # Для теста используем индекс который точно вызовет ошибку при некорректной реализации
    # В данном случае -1 НЕ вызовет ошибку в Python (вернёт последний элемент)
    # Используем -100 для гарантированной ошибки при отсутствии проверки границ
    with pytest.raises(IndexError):
        await UserSubscriptions.build_user_subs_slider_msg(-100, callback, mock_fsm_context)


@pytest.mark.asyncio
async def test_build_user_subs_slider_msg_invalid_index_out_of_bounds(mock_fsm_context, sample_user_subs_data):
    """Тест: build_user_subs_slider_msg выбрасывает IndexError при slider_idx >= len(user_subs)"""
    # Arrange
    mock_fsm_context.get_data = AsyncMock(return_value={'user_subs': sample_user_subs_data})
    
    user = TgUser(id=567890, username='out_bounds', first_name='Out', last_name='Bounds', is_bot=False)
    message = Message(message_id=10, date=datetime.now(), chat=Chat(id=567890, type='private'), from_user=user)
    callback = CallbackQuery(id='cb_10', from_user=user, chat_instance='ci', message=message, data='subs-user-pagen_100')
    
    # Act & Assert: ожидаем IndexError при индексе >= len(user_subs)
    with pytest.raises(IndexError):
        await UserSubscriptions.build_user_subs_slider_msg(len(sample_user_subs_data), callback, mock_fsm_context)


# ============================================================================
# C. show_price_offers() - 3 теста
# ============================================================================

@pytest.mark.asyncio
async def test_show_price_offers_success(mock_fsm_context, sample_user_subs_data, redis_client):
    """Тест: show_price_offers успешно возвращает текст и клавиатуру с ценовыми предложениями"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    mock_fsm_context.get_data = AsyncMock(return_value={'user_subs': sample_user_subs_data})
    fake_session = FakeAiohttpSession(json_data={}, status=200)
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=111111, username='offers_test', first_name='Offers', last_name='Test', is_bot=False)
    message = Message(message_id=11, date=datetime.now(), chat=Chat(id=111111, type='private'), from_user=user)
    callback = CallbackQuery(id='cb_11', from_user=user, chat_instance='ci', message=message, data='subs-user-upd_0')
    
    # Act
    text, kb = await UserSubscriptions.show_price_offers(0, redis_client, callback, mock_fsm_context, conn)
    
    # Assert
    assert text is not None
    assert kb is not None
    assert isinstance(text, str)
    assert len(text) > 0


@pytest.mark.asyncio
async def test_show_price_offers_calls_get_data(mock_fsm_context, sample_user_subs_data, redis_client):
    """Тест: show_price_offers вызывает state.get_data() для получения подписок"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    mock_fsm_context.get_data = AsyncMock(return_value={'user_subs': sample_user_subs_data})
    fake_session = FakeAiohttpSession(json_data={}, status=200)
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=222222, username='get_data_offers', first_name='GetData', last_name='Offers', is_bot=False)
    message = Message(message_id=12, date=datetime.now(), chat=Chat(id=222222, type='private'), from_user=user)
    callback = CallbackQuery(id='cb_12', from_user=user, chat_instance='ci', message=message, data='subs-user-upd_0')
    
    # Act
    await UserSubscriptions.show_price_offers(0, redis_client, callback, mock_fsm_context, conn)
    
    # Assert: get_data вызван
    mock_fsm_context.get_data.assert_called_once()


@pytest.mark.asyncio
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_show_price_offers_fallback_no_state(mock_callback_answer, mock_fsm_context, redis_client):
    """Тест: show_price_offers вызывает user_subscriptions_slider когда user_subs отсутствуют в state"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange: get_data возвращает пустой dict (нет user_subs)
    mock_fsm_context.get_data = AsyncMock(return_value={})
    fake_session = FakeAiohttpSession(json_data={'user_subs': []}, status=200)
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=333333, username='fallback_offers', first_name='Fallback', last_name='Offers', is_bot=False)
    message = Message(message_id=13, date=datetime.now(), chat=Chat(id=333333, type='private'), from_user=user)
    
    with patch.object(Message, 'answer', new_callable=AsyncMock):
        with patch('bot.core.handlers.subscriptions_shop.UserSubscriptions.user_subscriptions_slider', new_callable=AsyncMock) as mock_slider:
            callback = CallbackQuery(id='cb_13', from_user=user, chat_instance='ci', message=message, data='subs-user-upd_0')
            
            # Act
            result = await UserSubscriptions.show_price_offers(0, redis_client, callback, mock_fsm_context, conn)
            
            # Assert
            # 1. user_subscriptions_slider вызван
            mock_slider.assert_called_once()
            
            # 2. Возвращает (None, None)
            assert result == (None, None)


# ============================================================================
# D. give_issued_payment() - 4 теста
# ============================================================================

@pytest.mark.asyncio
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_give_issued_payment_success(mock_callback_answer, mock_fsm_context, sample_user_subs_data, redis_client):
    """Тест: give_issued_payment успешно получает ссылку на оплату и возвращает текст с клавиатурой"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    mock_fsm_context.get_data = AsyncMock(return_value={'user_subs': sample_user_subs_data})
    
    fake_session = FakeAiohttpSession(
        json_data={'payment_url': 'https://payment.example.com/pay/abc123'},
        status=200
    )
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=444444, username='payment_test', first_name='Payment', last_name='Test', is_bot=False)
    message = Message(message_id=14, date=datetime.now(), chat=Chat(id=444444, type='private'), from_user=user)
    callback = CallbackQuery(id='cb_14', from_user=user, chat_instance='ci', message=message, data='subs-user-offer_0_0')
    
    # Act
    text, kb = await UserSubscriptions.give_issued_payment(callback, redis_client, mock_fsm_context, conn, 0, 0)
    
    # Assert
    assert text is not None
    assert kb is not None
    assert isinstance(text, str)
    assert len(text) > 0


@pytest.mark.asyncio
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_give_issued_payment_calls_api_with_correct_params(
    mock_callback_answer,
    mock_fsm_context,
    sample_user_subs_data,
    redis_client
):
    """Тест: give_issued_payment вызывает API с правильными параметрами (tg_id, sub_plan_id, offer_id)"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    from bot.core.utils.anything import SubServiceUris
    
    # Arrange
    mock_fsm_context.get_data = AsyncMock(return_value={'user_subs': sample_user_subs_data})
    
    fake_session = FakeAiohttpSession(
        json_data={'payment_url': 'https://payment.example.com/pay/test'},
        status=200
    )
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=555555, username='api_params_test', first_name='API', last_name='Params', is_bot=False)
    message = Message(message_id=15, date=datetime.now(), chat=Chat(id=555555, type='private'), from_user=user)
    callback = CallbackQuery(id='cb_15', from_user=user, chat_instance='ci', message=message, data='subs-user-offer_0_0')
    
    # Act
    await UserSubscriptions.give_issued_payment(callback, redis_client, mock_fsm_context, conn, 0, 0)
    
    # Assert: проверяем параметры API запроса
    call = fake_session.request_calls[0]
    assert call['method'] == 'POST'
    assert SubServiceUris.get_payment_link in call['url']
    
    json_payload = call['kwargs']['json']
    assert json_payload['tg_id'] == 555555
    assert json_payload['sub_plan_id'] == sample_user_subs_data[0]['sub_plan_id']
    assert json_payload['offer_id'] == sample_user_subs_data[0]['offer_prices'][0]['offer_id']
    assert json_payload['description'] == sample_user_subs_data[0]['title']


@pytest.mark.asyncio
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_give_issued_payment_api_error(mock_callback_answer, mock_fsm_context, sample_user_subs_data, redis_client):
    """Тест: give_issued_payment обрабатывает ошибку API (order_success=False)"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange: API возвращает ошибку
    mock_fsm_context.get_data = AsyncMock(return_value={'user_subs': sample_user_subs_data})
    
    fake_session = FakeAiohttpSession(
        json_data={'error': 'Payment service unavailable'},
        status=500
    )
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=666666, username='api_error', first_name='API', last_name='Error', is_bot=False)
    message = Message(message_id=16, date=datetime.now(), chat=Chat(id=666666, type='private'), from_user=user)
    callback = CallbackQuery(id='cb_16', from_user=user, chat_instance='ci', message=message, data='subs-user-offer_0_0')
    
    # Act
    text, kb = await UserSubscriptions.give_issued_payment(callback, redis_client, mock_fsm_context, conn, 0, 0)
    
    # Assert: возвращает сообщение об ошибке и None для клавиатуры
    assert text is not None
    assert 'Не удалось сформировать заказ' in text
    assert kb is None


@pytest.mark.asyncio
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_give_issued_payment_fallback_no_state(mock_callback_answer, mock_fsm_context, redis_client):
    """Тест: give_issued_payment вызывает user_subscriptions_slider когда user_subs отсутствуют в state"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange: get_data возвращает пустой dict (нет user_subs)
    mock_fsm_context.get_data = AsyncMock(return_value={})
    fake_session = FakeAiohttpSession(json_data={'user_subs': []}, status=200)
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=777777, username='fallback_payment', first_name='Fallback', last_name='Payment', is_bot=False)
    message = Message(message_id=17, date=datetime.now(), chat=Chat(id=777777, type='private'), from_user=user)
    
    with patch.object(Message, 'answer', new_callable=AsyncMock):
        with patch('bot.core.handlers.subscriptions_shop.UserSubscriptions.user_subscriptions_slider', new_callable=AsyncMock) as mock_slider:
            callback = CallbackQuery(id='cb_17', from_user=user, chat_instance='ci', message=message, data='subs-user-offer_0_0')
            
            # Act
            result = await UserSubscriptions.give_issued_payment(callback, redis_client, mock_fsm_context, conn, 0, 0)
            
            # Assert
            # 1. user_subscriptions_slider вызван (fallback)
            mock_slider.assert_called_once()
            
            # 2. Возвращает (None, None)
            assert result == (None, None)
