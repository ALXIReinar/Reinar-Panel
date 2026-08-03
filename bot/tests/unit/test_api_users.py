"""
Тесты для API модуля (bot/core/api/divisions/).

Проверяет корректность работы методов:
- UsersAioHttp: save_user(), get_user_info()
- UserSubsAioHttp: all()
- SubPlansAioHttp: api_get_payment_link()
"""

import pytest
from aiohttp import ClientError

from bot.core.api.aiohttp_conn import SubServiceConn


# ============================================================================
# A. Успешные сценарии - 4 теста
# ============================================================================

@pytest.mark.asyncio
async def test_save_user_new_user_returns_data():
    """Тест: новый пользователь с return_data=True возвращает данные о регистрации"""
    from bot.tests.conftest import FakeAiohttpSession
    
    # Arrange: новый пользователь (insert_success=True, sub_count=0)
    fake_session = FakeAiohttpSession(
        json_data={
            'insert_success': True,
            'sub_count': 0,
            'user_id': 1,
            'registered_at': '2024-01-01T10:00:00'
        },
        status=200
    )
    
    conn = SubServiceConn(fake_session)
    
    # Act
    ok, data = await conn.users.save_user(
        tg_id=123456,
        tg_username='new_user',
        return_data=True
    )
    
    # Assert
    assert ok is True
    assert data['insert_success'] is True
    assert data['sub_count'] == 0
    assert data['user_id'] == 1
    assert 'registered_at' in data


@pytest.mark.asyncio
async def test_save_user_existing_user_returns_data():
    """Тест: существующий пользователь с return_data=True возвращает профиль с подписками"""
    from bot.tests.conftest import FakeAiohttpSession
    
    # Arrange: существующий пользователь (insert_success=False, sub_count>0)
    fake_session = FakeAiohttpSession(
        json_data={
            'insert_success': False,
            'id': 1,
            'sub_count': 2,
            'registered_at': '2023-12-01T10:00:00',
            'user_id': 1
        },
        status=200
    )
    
    conn = SubServiceConn(fake_session)
    
    # Act
    ok, data = await conn.users.save_user(
        tg_id=123456,
        tg_username='existing_user',
        return_data=True
    )
    
    # Assert
    assert ok is True
    assert data['insert_success'] is False
    assert data['sub_count'] == 2
    assert data['id'] == 1
    assert data['user_id'] == 1
    assert 'registered_at' in data


@pytest.mark.asyncio
async def test_save_user_without_return_data():
    """Тест: return_data=False возвращает HTTP 204 и пустой dict"""
    from bot.tests.conftest import FakeAiohttpSession
    
    # Arrange: без возврата данных (API возвращает 204 No Content)
    fake_session = FakeAiohttpSession(
        json_data={},
        status=204
    )
    
    conn = SubServiceConn(fake_session)
    
    # Act
    ok, data = await conn.users.save_user(
        tg_id=123456,
        tg_username='test_user',
        return_data=False
    )
    
    # Assert
    assert ok is True
    assert data == {}  # Пустой dict по умолчанию


@pytest.mark.asyncio
async def test_save_user_calls_correct_endpoint():
    """Тест: проверяет что вызывается правильный эндпоинт с правильными параметрами"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.utils.anything import SubServiceUris
    
    # Arrange
    fake_session = FakeAiohttpSession(
        json_data={'insert_success': True, 'sub_count': 0, 'user_id': 1},
        status=200
    )
    
    conn = SubServiceConn(fake_session)
    
    # Act
    await conn.users.save_user(
        tg_id=999888,
        tg_username='spy_user',
        return_data=True
    )
    
    # Assert: проверяем spy данные (используем request_calls, так как BaseAioHTTPClient использует session.request)
    assert len(fake_session.request_calls) == 1
    call = fake_session.request_calls[0]
    
    # Проверяем метод и URL
    assert call['method'] == 'POST'
    assert SubServiceUris.add_tg_user in call['url']
    
    # Проверяем JSON payload
    assert 'json' in call['kwargs']
    json_payload = call['kwargs']['json']
    assert json_payload['tg_id'] == 999888
    assert json_payload['tg_username'] == 'spy_user'
    assert json_payload['return_data'] is True


# ============================================================================
# B. Обработка ошибок - 2 теста
# ============================================================================

@pytest.mark.asyncio
async def test_save_user_network_error():
    """Тест: сетевая ошибка возвращает ok=False с исключением"""
    from bot.tests.conftest import FakeAiohttpSession
    
    # Arrange: имитация сетевой ошибки
    fake_session = FakeAiohttpSession(raise_error=True)
    
    conn = SubServiceConn(fake_session)
    
    # Act
    ok, data = await conn.users.save_user(
        tg_id=123456,
        tg_username='network_fail',
        return_data=True
    )
    
    # Assert
    assert ok is False
    assert isinstance(data, ClientError)


@pytest.mark.asyncio
async def test_save_user_api_error_500():
    """Тест: API возвращает 500 - обрабатываем как ошибку"""
    from bot.tests.conftest import FakeAiohttpSession
    
    # Arrange: имитация 500 Internal Server Error
    fake_session = FakeAiohttpSession(
        json_data={'error': 'Internal Server Error'},
        status=500
    )
    
    conn = SubServiceConn(fake_session)
    
    # Act
    ok, data = await conn.users.save_user(
        tg_id=123456,
        tg_username='error_user',
        return_data=True
    )
    
    # Assert
    assert ok is False
    assert isinstance(data, Exception)


# ============================================================================
# C. Параметры запроса - 2 теста
# ============================================================================

@pytest.mark.asyncio
async def test_save_user_with_username():
    """Тест: username передаётся в API"""
    from bot.tests.conftest import FakeAiohttpSession
    
    # Arrange
    fake_session = FakeAiohttpSession(
        json_data={'insert_success': True, 'sub_count': 0, 'user_id': 1},
        status=200
    )
    
    conn = SubServiceConn(fake_session)
    
    # Act
    await conn.users.save_user(
        tg_id=111222,
        tg_username='john_doe',
        return_data=False
    )
    
    # Assert
    call = fake_session.request_calls[0]
    assert call['kwargs']['json']['tg_username'] == 'john_doe'


@pytest.mark.asyncio
async def test_save_user_without_username():
    """Тест: пользователь без username (None) корректно обрабатывается"""
    from bot.tests.conftest import FakeAiohttpSession
    
    # Arrange
    fake_session = FakeAiohttpSession(
        json_data={'insert_success': True, 'sub_count': 0, 'user_id': 1},
        status=200
    )
    
    conn = SubServiceConn(fake_session)
    
    # Act
    await conn.users.save_user(
        tg_id=333444,
        tg_username=None,  # Нет username
        return_data=False
    )
    
    # Assert: проверяем что None передаётся в API
    call = fake_session.request_calls[0]
    assert call['kwargs']['json']['tg_username'] is None


# ============================================================================
# D. get_user_info() - 5 тестов
# ============================================================================

@pytest.mark.asyncio
async def test_get_user_info_success():
    """Тест: get_user_info успешно возвращает данные пользователя"""
    from bot.tests.conftest import FakeAiohttpSession
    
    # Arrange
    user_data = {
        'id': 1,
        'registered_at': '2023-12-01T10:00:00',
        'sub_count': 2
    }
    
    fake_session = FakeAiohttpSession(json_data=user_data, status=200)
    conn = SubServiceConn(fake_session)
    
    # Act
    ok, data = await conn.users.get_user_info(tg_id=123456)
    
    # Assert
    assert ok is True
    assert data['id'] == 1
    assert data['sub_count'] == 2
    assert 'registered_at' in data


@pytest.mark.asyncio
async def test_get_user_info_calls_correct_endpoint():
    """Тест: get_user_info вызывает правильный эндпоинт с параметрами"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.utils.anything import SubServiceUris
    
    # Arrange
    fake_session = FakeAiohttpSession(
        json_data={'id': 1, 'sub_count': 0},
        status=200
    )
    
    conn = SubServiceConn(fake_session)
    
    # Act
    await conn.users.get_user_info(tg_id=999888)
    
    # Assert: проверяем spy данные
    assert len(fake_session.request_calls) == 1
    call = fake_session.request_calls[0]
    
    # Проверяем метод и URL
    assert call['method'] == 'GET'
    assert SubServiceUris.get_user_profile in call['url']
    
    # Проверяем query параметры
    assert 'params' in call['kwargs']
    assert call['kwargs']['params']['tg_id'] == 999888


@pytest.mark.asyncio
async def test_get_user_info_api_error():
    """Тест: get_user_info обрабатывает ошибку API и возвращает False, {}"""
    from bot.tests.conftest import FakeAiohttpSession
    
    # Arrange: API возвращает 500
    fake_session = FakeAiohttpSession(
        json_data={'error': 'Internal Server Error'},
        status=500
    )
    
    conn = SubServiceConn(fake_session)
    
    # Act
    ok, data = await conn.users.get_user_info(tg_id=123456)
    
    # Assert: возвращает False и пустой dict
    assert ok is False
    assert data == {}


@pytest.mark.asyncio
async def test_get_user_info_network_error():
    """Тест: get_user_info обрабатывает сетевую ошибку"""
    from bot.tests.conftest import FakeAiohttpSession
    
    # Arrange: имитация сетевой ошибки
    fake_session = FakeAiohttpSession(raise_error=True)
    
    conn = SubServiceConn(fake_session)
    
    # Act
    ok, data = await conn.users.get_user_info(tg_id=123456)
    
    # Assert
    assert ok is False
    assert data == {}


@pytest.mark.asyncio
async def test_get_user_info_with_valid_tg_id():
    """Тест: get_user_info передаёт tg_id в параметрах запроса"""
    from bot.tests.conftest import FakeAiohttpSession
    
    # Arrange
    fake_session = FakeAiohttpSession(
        json_data={'id': 1, 'sub_count': 3},
        status=200
    )
    
    conn = SubServiceConn(fake_session)
    
    # Act
    await conn.users.get_user_info(tg_id=777888)
    
    # Assert: проверяем что tg_id передан правильно
    call = fake_session.request_calls[0]
    assert call['kwargs']['params']['tg_id'] == 777888


# ============================================================================
# E. UserSubsAioHttp.all() - 4 теста
# ============================================================================

@pytest.mark.asyncio
async def test_user_subs_all_success():
    """Тест: user_subs.all() успешно возвращает список подписок пользователя"""
    from bot.tests.conftest import FakeAiohttpSession
    
    # Arrange
    user_subs_data = {
        'user_subs': [
            {'user_sub_id': 1, 'sub_plan_id': 1, 'is_active': True},
            {'user_sub_id': 2, 'sub_plan_id': 2, 'is_active': True}
        ]
    }
    
    fake_session = FakeAiohttpSession(json_data=user_subs_data, status=200)
    conn = SubServiceConn(fake_session)
    
    # Act
    ok, data = await conn.user_subs.all(tg_id=123456)
    
    # Assert
    assert ok is True
    assert len(data) == 2
    assert data[0]['user_sub_id'] == 1
    assert data[1]['user_sub_id'] == 2


@pytest.mark.asyncio
async def test_user_subs_all_calls_correct_endpoint():
    """Тест: user_subs.all() вызывает правильный эндпоинт с tg_id"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.utils.anything import SubServiceUris
    
    # Arrange
    fake_session = FakeAiohttpSession(
        json_data={'user_subs': []},
        status=200
    )
    
    conn = SubServiceConn(fake_session)
    
    # Act
    await conn.user_subs.all(tg_id=999888)
    
    # Assert
    assert len(fake_session.request_calls) == 1
    call = fake_session.request_calls[0]
    
    assert call['method'] == 'GET'
    assert SubServiceUris.get_user_subs_all in call['url']
    assert call['kwargs']['params']['tg_id'] == 999888


@pytest.mark.asyncio
async def test_user_subs_all_api_error():
    """Тест: user_subs.all() обрабатывает ошибку API и возвращает False, []"""
    from bot.tests.conftest import FakeAiohttpSession
    
    # Arrange: API возвращает 500
    fake_session = FakeAiohttpSession(
        json_data={'error': 'Internal Server Error'},
        status=500
    )
    
    conn = SubServiceConn(fake_session)
    
    # Act
    ok, data = await conn.user_subs.all(tg_id=123456)
    
    # Assert
    assert ok is False
    assert data == []


@pytest.mark.asyncio
async def test_user_subs_all_network_error():
    """Тест: user_subs.all() обрабатывает сетевую ошибку"""
    from bot.tests.conftest import FakeAiohttpSession
    
    # Arrange
    fake_session = FakeAiohttpSession(raise_error=True)
    
    conn = SubServiceConn(fake_session)
    
    # Act
    ok, data = await conn.user_subs.all(tg_id=123456)
    
    # Assert
    assert ok is False
    assert data == []


# ============================================================================
# F. SubPlansAioHttp.api_get_payment_link() - 4 теста
# ============================================================================

@pytest.mark.asyncio
async def test_api_get_payment_link_success():
    """Тест: api_get_payment_link успешно возвращает ссылку на оплату"""
    from bot.tests.conftest import FakeAiohttpSession
    
    # Arrange
    payment_data = {
        'payment_url': 'https://payment.example.com/pay/abc123'
    }
    
    fake_session = FakeAiohttpSession(json_data=payment_data, status=200)
    conn = SubServiceConn(fake_session)
    
    # Act
    ok, payment_url = await conn.sub_plans.api_get_payment_link(
        tg_id=123456,
        sub_plan_id=1,
        offer_id=1,
        description='Test Plan'
    )
    
    # Assert
    assert ok is True
    assert payment_url == 'https://payment.example.com/pay/abc123'


@pytest.mark.asyncio
async def test_api_get_payment_link_calls_correct_endpoint():
    """Тест: api_get_payment_link вызывает правильный эндпоинт с параметрами"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.utils.anything import SubServiceUris
    
    # Arrange
    fake_session = FakeAiohttpSession(
        json_data={'payment_url': 'https://test.com'},
        status=200
    )
    
    conn = SubServiceConn(fake_session)
    
    # Act
    await conn.sub_plans.api_get_payment_link(
        tg_id=999888,
        sub_plan_id=5,
        offer_id=10,
        description='Premium Plan'
    )
    
    # Assert
    assert len(fake_session.request_calls) == 1
    call = fake_session.request_calls[0]
    
    assert call['method'] == 'POST'
    assert SubServiceUris.get_payment_link in call['url']
    
    json_payload = call['kwargs']['json']
    assert json_payload['tg_id'] == 999888
    assert json_payload['sub_plan_id'] == 5
    assert json_payload['offer_id'] == 10
    assert json_payload['description'] == 'Premium Plan'


@pytest.mark.asyncio
async def test_api_get_payment_link_api_error():
    """Тест: api_get_payment_link обрабатывает ошибку API"""
    from bot.tests.conftest import FakeAiohttpSession
    
    # Arrange: API возвращает 500
    fake_session = FakeAiohttpSession(
        json_data={'error': 'Payment service unavailable'},
        status=500
    )
    
    conn = SubServiceConn(fake_session)
    
    # Act
    ok, data = await conn.sub_plans.api_get_payment_link(
        tg_id=123456,
        sub_plan_id=1,
        offer_id=1,
        description='Test'
    )
    
    # Assert
    assert ok is False


@pytest.mark.asyncio
async def test_api_get_payment_link_network_error():
    """Тест: api_get_payment_link обрабатывает сетевую ошибку"""
    from bot.tests.conftest import FakeAiohttpSession
    
    # Arrange
    fake_session = FakeAiohttpSession(raise_error=True)
    
    conn = SubServiceConn(fake_session)
    
    # Act
    ok, data = await conn.sub_plans.api_get_payment_link(
        tg_id=123456,
        sub_plan_id=1,
        offer_id=1,
        description='Test'
    )
    
    # Assert
    assert ok is False


# ============================================================================
# E. SubPlansAioHttp.all() - 4 теста
# ============================================================================

@pytest.mark.asyncio
async def test_sub_plans_all_success():
    """Тест: sub_plans.all() успешно возвращает список тарифных планов"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    shop_plans_data = {
        'sub_plans': [
            {'id': 1, 'title': 'Basic', 'description': 'Basic plan', 'offer_prices': []},
            {'id': 2, 'title': 'Premium', 'description': 'Premium plan', 'offer_prices': []}
        ]
    }
    
    fake_session = FakeAiohttpSession(json_data=shop_plans_data, status=200)
    conn = SubServiceConn(fake_session)
    
    # Act
    ok, data = await conn.sub_plans.all()
    
    # Assert
    assert ok is True
    assert len(data) == 2
    assert data[0]['id'] == 1
    assert data[1]['id'] == 2


@pytest.mark.asyncio
async def test_sub_plans_all_calls_correct_endpoint():
    """Тест: sub_plans.all() вызывает правильный эндпоинт"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    from bot.core.utils.anything import SubServiceUris
    
    # Arrange
    fake_session = FakeAiohttpSession(
        json_data={'sub_plans': []},
        status=200
    )
    
    conn = SubServiceConn(fake_session)
    
    # Act
    await conn.sub_plans.all()
    
    # Assert
    assert len(fake_session.request_calls) == 1
    call = fake_session.request_calls[0]
    
    assert call['method'] == 'GET'
    assert SubServiceUris.get_sub_plans_all in call['url']


@pytest.mark.asyncio
async def test_sub_plans_all_api_error():
    """Тест: sub_plans.all() обрабатывает ошибку API и возвращает False, данные ошибки"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange: API возвращает 500
    fake_session = FakeAiohttpSession(
        json_data={'error': 'Internal Server Error'},
        status=500
    )
    
    conn = SubServiceConn(fake_session)
    
    # Act
    ok, data = await conn.sub_plans.all()
    
    # Assert
    assert ok is False


@pytest.mark.asyncio
async def test_sub_plans_all_network_error():
    """Тест: sub_plans.all() обрабатывает сетевую ошибку"""
    from bot.tests.conftest import FakeAiohttpSession
    from bot.core.api.aiohttp_conn import SubServiceConn
    
    # Arrange
    fake_session = FakeAiohttpSession(raise_error=True)
    
    conn = SubServiceConn(fake_session)
    
    # Act
    ok, data = await conn.sub_plans.all()
    
    # Assert
    assert ok is False
