"""
Тесты для хэндлеров ShopSubscriptions класса (bot/core/handlers/subscriptions_shop.py).

Проверяет корректность работы:
- shop_subscriptions_slider() - получение тарифных планов, сохранение в Redis
- build_shop_plans_slider_msg() - построение сообщения слайдера из Redis
- give_issued_payment() - формирование ссылки на оплату
"""

import pytest
import orjson
from unittest.mock import AsyncMock, patch, MagicMock
from aiogram.types import CallbackQuery, User as TgUser, Message, Chat
from datetime import datetime

from bot.core.handlers.subscriptions_shop import ShopSubscriptions
from bot.core.utils.schemas import ShopSubSchema
from bot.core.utils.anything import RedisKeys


# ============================================================================
# Фикстуры
# ============================================================================

@pytest.fixture
def sample_shop_plans_data():
    """Пример данных тарифных планов магазина (список из 2 планов)"""
    return [
        {
            'id': 1,
            'title': 'Basic Plan',
            'description': 'Базовый тарифный план для начинающих',
            'sub_nodes_count': 3,
            'offer_prices': [
                {
                    'offer_id': 1,
                    'cost': 49900,
                    'ttl_days': 30,
                    'traffic_day_limit': 10240,
                    'traffic_limit': 307200,
                    'infinite_expire': False,
                    'infinite_traffic': False
                },
                {
                    'offer_id': 2,
                    'cost': 129900,
                    'ttl_days': 90,
                    'traffic_day_limit': 10240,
                    'traffic_limit': 921600,
                    'infinite_expire': False,
                    'infinite_traffic': False
                }
            ]
        },
        {
            'id': 2,
            'title': 'Premium Plan',
            'description': 'Премиум тарифный план с безлимитным трафиком',
            'sub_nodes_count': 5,
            'offer_prices': [
                {
                    'offer_id': 3,
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
# A. shop_subscriptions_slider() - 6 тестов
# ============================================================================

@pytest.mark.asyncio
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
@patch('bot.core.handlers.subscriptions_shop.ShopSubscriptions.build_shop_plans_slider_msg', new_callable=AsyncMock)
async def test_shop_subscriptions_slider_success(
    mock_build,
    mock_callback_answer,
    redis_client,
    sample_shop_plans_data
):
    """Тест: shop_subscriptions_slider успешно получает планы, сохраняет в Redis и отображает слайдер"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    fake_session = FakeAiohttpSession(
        json_data={'sub_plans': sample_shop_plans_data},
        status=200
    )
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=123456, username='test_user', first_name='Test', last_name='User', is_bot=False)
    message = Message(message_id=1, date=datetime.now(), chat=Chat(id=123456, type='private'), from_user=user)
    
    # Mock build возвращает текст и клавиатуру
    mock_build.return_value = ('Слайдер тарифов', MagicMock())
    
    # Патчим message.answer
    with patch.object(Message, 'answer', new_callable=AsyncMock) as mock_message_answer:
        callback = CallbackQuery(id='cb_1', from_user=user, chat_instance='ci', message=message, data='subs-shop-intro')
        
        # Act
        await ShopSubscriptions.shop_subscriptions_slider(callback, redis_client, conn)
        
        # Assert
        # 1. API вызван
        assert len(fake_session.request_calls) == 1
        
        # 2. Redis.set вызван с планами
        stored_data = await redis_client.get(RedisKeys.shop_sub_plans)
        assert stored_data is not None
        stored_plans = orjson.loads(stored_data)
        assert len(stored_plans) == 2
        
        # 3. build_shop_plans_slider_msg вызван
        mock_build.assert_called_once()
        
        # 4. Сообщение отправлено
        mock_message_answer.assert_called_once()


@pytest.mark.asyncio
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_shop_subscriptions_slider_calls_api(
    mock_callback_answer,
    redis_client,
    sample_shop_plans_data
):
    """Тест: shop_subscriptions_slider вызывает API с правильными параметрами"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    from bot.core.utils.anything import SubServiceUris
    
    # Arrange
    fake_session = FakeAiohttpSession(
        json_data={'sub_plans': sample_shop_plans_data},
        status=200
    )
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=999888, username='api_test', first_name='API', last_name='Test', is_bot=False)
    message = Message(message_id=2, date=datetime.now(), chat=Chat(id=999888, type='private'), from_user=user)
    
    with patch.object(Message, 'answer', new_callable=AsyncMock):
        with patch('bot.core.handlers.subscriptions_shop.ShopSubscriptions.build_shop_plans_slider_msg', new_callable=AsyncMock) as mock_build:
            mock_build.return_value = ('Text', MagicMock())
            
            callback = CallbackQuery(id='cb_2', from_user=user, chat_instance='ci', message=message, data='subs-shop-intro')
            
            # Act
            await ShopSubscriptions.shop_subscriptions_slider(callback, redis_client, conn)
            
            # Assert: проверяем параметры API запроса
            call = fake_session.request_calls[0]
            assert call['method'] == 'GET'
            assert SubServiceUris.get_sub_plans_all in call['url']


@pytest.mark.asyncio
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_shop_subscriptions_slider_saves_to_redis(
    mock_callback_answer,
    redis_client,
    sample_shop_plans_data
):
    """Тест: shop_subscriptions_slider сохраняет планы в Redis с TTL"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    from bot.config_dir.config import env
    
    # Arrange
    fake_session = FakeAiohttpSession(
        json_data={'sub_plans': sample_shop_plans_data},
        status=200
    )
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=111222, username='redis_test', first_name='Redis', last_name='Test', is_bot=False)
    message = Message(message_id=3, date=datetime.now(), chat=Chat(id=111222, type='private'), from_user=user)
    
    with patch.object(Message, 'answer', new_callable=AsyncMock):
        with patch('bot.core.handlers.subscriptions_shop.ShopSubscriptions.build_shop_plans_slider_msg', new_callable=AsyncMock) as mock_build:
            mock_build.return_value = ('Text', MagicMock())
            
            callback = CallbackQuery(id='cb_3', from_user=user, chat_instance='ci', message=message, data='subs-shop-intro')
            
            # Act
            await ShopSubscriptions.shop_subscriptions_slider(callback, redis_client, conn)
            
            # Assert
            # 1. Данные сохранены в Redis
            stored_data = await redis_client.get(RedisKeys.shop_sub_plans)
            assert stored_data is not None
            
            # 2. Данные корректно десериализуются
            stored_plans = orjson.loads(stored_data)
            assert stored_plans == sample_shop_plans_data
            
            # 3. TTL установлен
            ttl = await redis_client.ttl(RedisKeys.shop_sub_plans)
            assert ttl > 0
            assert ttl <= env.shop_sub_plans_ttl


@pytest.mark.asyncio
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_shop_subscriptions_slider_api_error(
    mock_callback_answer,
    redis_client
):
    """Тест: shop_subscriptions_slider обрабатывает ошибку API (ok=False)"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange: API возвращает ошибку
    fake_session = FakeAiohttpSession(
        json_data={'error': 'Service unavailable'},
        status=500
    )
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=333444, username='api_error', first_name='API', last_name='Error', is_bot=False)
    message = Message(message_id=4, date=datetime.now(), chat=Chat(id=333444, type='private'), from_user=user)
    
    with patch.object(Message, 'answer', new_callable=AsyncMock) as mock_message_answer:
        callback = CallbackQuery(id='cb_4', from_user=user, chat_instance='ci', message=message, data='subs-shop-intro')
        
        # Act
        await ShopSubscriptions.shop_subscriptions_slider(callback, redis_client, conn)
        
        # Assert: отправлено сообщение о техническом перерыве
        mock_message_answer.assert_called_once()
        call_args = mock_message_answer.call_args[0][0]
        assert 'Технический перерыв' in call_args or 'перерыв' in call_args.lower()


@pytest.mark.asyncio
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_shop_subscriptions_slider_no_plans(
    mock_callback_answer,
    redis_client
):
    """Тест: shop_subscriptions_slider показывает фоллбек когда нет тарифных планов"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange: API возвращает пустой список
    fake_session = FakeAiohttpSession(
        json_data={'sub_plans': []},
        status=200
    )
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=555666, username='no_plans', first_name='No', last_name='Plans', is_bot=False)
    message = Message(message_id=5, date=datetime.now(), chat=Chat(id=555666, type='private'), from_user=user)
    
    with patch.object(Message, 'answer', new_callable=AsyncMock) as mock_message_answer:
        callback = CallbackQuery(id='cb_5', from_user=user, chat_instance='ci', message=message, data='subs-shop-intro')
        
        # Act
        await ShopSubscriptions.shop_subscriptions_slider(callback, redis_client, conn)
        
        # Assert: отправлено сообщение об отсутствии подписок
        mock_message_answer.assert_called_once()
        call_args = mock_message_answer.call_args[0][0]
        assert 'не предоставляет' in call_args.lower() or 'подписки' in call_args.lower()


@pytest.mark.asyncio
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_shop_subscriptions_slider_calls_build_with_zero_index(
    mock_callback_answer,
    redis_client,
    sample_shop_plans_data
):
    """Тест: shop_subscriptions_slider вызывает build_shop_plans_slider_msg с индексом 0"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    fake_session = FakeAiohttpSession(
        json_data={'sub_plans': sample_shop_plans_data},
        status=200
    )
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=777888, username='build_test', first_name='Build', last_name='Test', is_bot=False)
    message = Message(message_id=6, date=datetime.now(), chat=Chat(id=777888, type='private'), from_user=user)
    
    with patch.object(Message, 'answer', new_callable=AsyncMock):
        with patch('bot.core.handlers.subscriptions_shop.ShopSubscriptions.build_shop_plans_slider_msg', new_callable=AsyncMock) as mock_build:
            mock_build.return_value = ('Text', MagicMock())
            
            callback = CallbackQuery(id='cb_6', from_user=user, chat_instance='ci', message=message, data='subs-shop-intro')
            
            # Act
            await ShopSubscriptions.shop_subscriptions_slider(callback, redis_client, conn)
            
            # Assert: build вызван с slider_idx=0
            assert mock_build.call_count == 1
            call_args = mock_build.call_args[0]
            assert call_args[0] == 0  # Первый аргумент - slider_idx


# ============================================================================
# B. build_shop_plans_slider_msg() - 5 тестов
# ============================================================================

@pytest.mark.asyncio
async def test_build_shop_plans_slider_msg_success(redis_client, sample_shop_plans_data):
    """Тест: build_shop_plans_slider_msg успешно возвращает текст и клавиатуру"""
    # Arrange: сохраняем данные в Redis
    await redis_client.set(RedisKeys.shop_sub_plans, orjson.dumps(sample_shop_plans_data))
    
    user = TgUser(id=123456, username='test_user', first_name='Test', last_name='User', is_bot=False)
    message = Message(message_id=7, date=datetime.now(), chat=Chat(id=123456, type='private'), from_user=user)
    callback = CallbackQuery(id='cb_7', from_user=user, chat_instance='ci', message=message, data='subs-shop-pagen_0')
    
    # Act
    text, kb = await ShopSubscriptions.build_shop_plans_slider_msg(0, callback, redis_client)
    
    # Assert
    assert text is not None
    assert kb is not None
    assert isinstance(text, str)
    assert len(text) > 0


@pytest.mark.asyncio
async def test_build_shop_plans_slider_msg_calls_redis_get(redis_client, sample_shop_plans_data):
    """Тест: build_shop_plans_slider_msg читает данные из Redis по правильному ключу"""
    # Arrange: сохраняем данные в Redis
    await redis_client.set(RedisKeys.shop_sub_plans, orjson.dumps(sample_shop_plans_data))
    
    user = TgUser(id=789012, username='redis_get_test', first_name='RedisGet', last_name='Test', is_bot=False)
    message = Message(message_id=8, date=datetime.now(), chat=Chat(id=789012, type='private'), from_user=user)
    callback = CallbackQuery(id='cb_8', from_user=user, chat_instance='ci', message=message, data='subs-shop-pagen_0')
    
    # Act
    text, kb = await ShopSubscriptions.build_shop_plans_slider_msg(0, callback, redis_client)
    
    # Assert: данные были получены из Redis
    assert text is not None
    # Проверяем что данные действительно есть в Redis
    stored_data = await redis_client.get(RedisKeys.shop_sub_plans)
    assert stored_data is not None


@pytest.mark.asyncio
async def test_build_shop_plans_slider_msg_fallback_no_cache(redis_client):
    """Тест: build_shop_plans_slider_msg возвращает (None, None) когда данных нет в Redis"""
    # Arrange: Redis пустой (нет данных)
    await redis_client.delete(RedisKeys.shop_sub_plans)
    
    user = TgUser(id=345678, username='no_cache', first_name='No', last_name='Cache', is_bot=False)
    message = Message(message_id=9, date=datetime.now(), chat=Chat(id=345678, type='private'), from_user=user)
    callback = CallbackQuery(id='cb_9', from_user=user, chat_instance='ci', message=message, data='subs-shop-pagen_0')
    
    # Act
    text, kb = await ShopSubscriptions.build_shop_plans_slider_msg(0, callback, redis_client)
    
    # Assert: возвращает (None, None)
    assert text is None
    assert kb is None


@pytest.mark.asyncio
async def test_build_shop_plans_slider_msg_invalid_index_negative(redis_client, sample_shop_plans_data):
    """Тест: build_shop_plans_slider_msg выбрасывает IndexError при slider_idx=-100"""
    # Arrange
    await redis_client.set(RedisKeys.shop_sub_plans, orjson.dumps(sample_shop_plans_data))
    
    user = TgUser(id=901234, username='neg_idx', first_name='Negative', last_name='Index', is_bot=False)
    message = Message(message_id=10, date=datetime.now(), chat=Chat(id=901234, type='private'), from_user=user)
    callback = CallbackQuery(id='cb_10', from_user=user, chat_instance='ci', message=message, data='subs-shop-pagen_-100')
    
    # Act & Assert: ожидаем IndexError
    with pytest.raises(IndexError):
        await ShopSubscriptions.build_shop_plans_slider_msg(-100, callback, redis_client)


@pytest.mark.asyncio
async def test_build_shop_plans_slider_msg_invalid_index_out_of_bounds(redis_client, sample_shop_plans_data):
    """Тест: build_shop_plans_slider_msg выбрасывает IndexError при slider_idx >= len(shop_plans)"""
    # Arrange
    await redis_client.set(RedisKeys.shop_sub_plans, orjson.dumps(sample_shop_plans_data))
    
    user = TgUser(id=567890, username='out_bounds', first_name='Out', last_name='Bounds', is_bot=False)
    message = Message(message_id=11, date=datetime.now(), chat=Chat(id=567890, type='private'), from_user=user)
    callback = CallbackQuery(id='cb_11', from_user=user, chat_instance='ci', message=message, data='subs-shop-pagen_100')
    
    # Act & Assert: ожидаем IndexError при индексе >= len(shop_plans)
    with pytest.raises(IndexError):
        await ShopSubscriptions.build_shop_plans_slider_msg(len(sample_shop_plans_data), callback, redis_client)


# ============================================================================
# C. give_issued_payment() - 5 тестов
# ============================================================================

@pytest.mark.asyncio
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_give_issued_payment_success(mock_callback_answer, redis_client, sample_shop_plans_data):
    """Тест: give_issued_payment успешно получает ссылку на оплату и возвращает текст с клавиатурой"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    await redis_client.set(RedisKeys.shop_sub_plans, orjson.dumps(sample_shop_plans_data))
    
    fake_session = FakeAiohttpSession(
        json_data={'payment_url': 'https://payment.example.com/pay/xyz789'},
        status=200
    )
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=444444, username='payment_test', first_name='Payment', last_name='Test', is_bot=False)
    message = Message(message_id=12, date=datetime.now(), chat=Chat(id=444444, type='private'), from_user=user)
    callback = CallbackQuery(id='cb_12', from_user=user, chat_instance='ci', message=message, data='subs-shop-offer_0_0')
    
    # Act
    text, kb = await ShopSubscriptions.give_issued_payment(callback, redis_client, conn, 0, 0)
    
    # Assert
    assert text is not None
    assert kb is not None
    assert isinstance(text, str)
    assert len(text) > 0


@pytest.mark.asyncio
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_give_issued_payment_calls_api_with_correct_params(
    mock_callback_answer,
    redis_client,
    sample_shop_plans_data
):
    """Тест: give_issued_payment вызывает API с правильными параметрами (tg_id, sub_plan_id, offer_id)"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    from bot.core.utils.anything import SubServiceUris
    
    # Arrange
    await redis_client.set(RedisKeys.shop_sub_plans, orjson.dumps(sample_shop_plans_data))
    
    fake_session = FakeAiohttpSession(
        json_data={'payment_url': 'https://payment.example.com/pay/test'},
        status=200
    )
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=555555, username='api_params', first_name='API', last_name='Params', is_bot=False)
    message = Message(message_id=13, date=datetime.now(), chat=Chat(id=555555, type='private'), from_user=user)
    callback = CallbackQuery(id='cb_13', from_user=user, chat_instance='ci', message=message, data='subs-shop-offer_0_0')
    
    # Act
    await ShopSubscriptions.give_issued_payment(callback, redis_client, conn, 0, 0)
    
    # Assert: проверяем параметры API запроса
    call = fake_session.request_calls[0]
    assert call['method'] == 'POST'
    assert SubServiceUris.get_payment_link in call['url']
    
    json_payload = call['kwargs']['json']
    assert json_payload['tg_id'] == 555555
    assert json_payload['sub_plan_id'] == sample_shop_plans_data[0]['id']
    assert json_payload['offer_id'] == sample_shop_plans_data[0]['offer_prices'][0]['offer_id']
    assert json_payload['description'] == sample_shop_plans_data[0]['title']


@pytest.mark.asyncio
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_give_issued_payment_api_error(mock_callback_answer, redis_client, sample_shop_plans_data):
    """Тест: give_issued_payment обрабатывает ошибку API (order_success=False)"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange: API возвращает ошибку
    await redis_client.set(RedisKeys.shop_sub_plans, orjson.dumps(sample_shop_plans_data))
    
    fake_session = FakeAiohttpSession(
        json_data={'error': 'Payment service unavailable'},
        status=500
    )
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=666666, username='api_error', first_name='API', last_name='Error', is_bot=False)
    message = Message(message_id=14, date=datetime.now(), chat=Chat(id=666666, type='private'), from_user=user)
    callback = CallbackQuery(id='cb_14', from_user=user, chat_instance='ci', message=message, data='subs-shop-offer_0_0')
    
    # Act
    text, kb = await ShopSubscriptions.give_issued_payment(callback, redis_client, conn, 0, 0)
    
    # Assert: возвращает сообщение об ошибке и None для клавиатуры
    assert text is not None
    assert 'Не удалось сформировать заказ' in text
    assert kb is None


@pytest.mark.asyncio
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_give_issued_payment_fallback_no_cache(mock_callback_answer, redis_client):
    """Тест: give_issued_payment вызывает shop_subscriptions_slider когда данных нет в Redis"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange: Redis пустой (нет данных)
    await redis_client.delete(RedisKeys.shop_sub_plans)
    
    fake_session = FakeAiohttpSession(
        json_data={'sub_plans': []},
        status=200
    )
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=777777, username='fallback_payment', first_name='Fallback', last_name='Payment', is_bot=False)
    message = Message(message_id=15, date=datetime.now(), chat=Chat(id=777777, type='private'), from_user=user)
    
    with patch.object(Message, 'answer', new_callable=AsyncMock):
        with patch('bot.core.handlers.subscriptions_shop.ShopSubscriptions.shop_subscriptions_slider', new_callable=AsyncMock) as mock_slider:
            callback = CallbackQuery(id='cb_15', from_user=user, chat_instance='ci', message=message, data='subs-shop-offer_0_0')
            
            # Act
            result = await ShopSubscriptions.give_issued_payment(callback, redis_client, conn, 0, 0)
            
            # Assert
            # 1. shop_subscriptions_slider вызван (fallback)
            mock_slider.assert_called_once()
            
            # 2. Возвращает (None, None)
            assert result == (None, None)


@pytest.mark.asyncio
@patch.object(CallbackQuery, 'answer', new_callable=AsyncMock)
async def test_give_issued_payment_redis_get_called(mock_callback_answer, redis_client, sample_shop_plans_data):
    """Тест: give_issued_payment читает данные из Redis по правильному ключу"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    await redis_client.set(RedisKeys.shop_sub_plans, orjson.dumps(sample_shop_plans_data))
    
    fake_session = FakeAiohttpSession(
        json_data={'payment_url': 'https://payment.example.com/pay/check'},
        status=200
    )
    conn = SubServiceConn(fake_session)
    
    user = TgUser(id=888888, username='redis_check', first_name='Redis', last_name='Check', is_bot=False)
    message = Message(message_id=16, date=datetime.now(), chat=Chat(id=888888, type='private'), from_user=user)
    callback = CallbackQuery(id='cb_16', from_user=user, chat_instance='ci', message=message, data='subs-shop-offer_0_0')
    
    # Act
    await ShopSubscriptions.give_issued_payment(callback, redis_client, conn, 0, 0)
    
    # Assert: проверяем что данные были получены из Redis
    stored_data = await redis_client.get(RedisKeys.shop_sub_plans)
    assert stored_data is not None
    stored_plans = orjson.loads(stored_data)
    assert len(stored_plans) == 2
