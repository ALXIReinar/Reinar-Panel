"""
Тесты для системы плейсхолдеров (PlaceholderResolver).

Проверяет корректность подстановки плейсхолдеров в текстовые шаблоны.
Покрывает все методы и edge cases.
"""

import pytest
from datetime import datetime, timezone
from aiogram.types import User as TgUser, Message, CallbackQuery, Chat

from bot.core.utils.placeholders import PlaceholderResolver
from bot.core.utils.schemas import UserSchema, UserSubSchema, ShopSubSchema, SubOfferSchema


# ============================================================================
# A. add_message() - 5 тестов
# ============================================================================

@pytest.mark.unit
def test_add_message_all_fields():
    """Тест: add_message() извлекает все поля"""
    resolver = PlaceholderResolver()
    user = TgUser(id=123, username="john_doe", first_name="John", last_name="Doe", is_bot=False)
    message = Message(message_id=1, date=datetime.now(), chat=Chat(id=123, type="private"), from_user=user)
    
    resolver.add_message(message)
    result = resolver.resolve("{USER_TG_ID}|{USER_TG_USERNAME}|{USER_TG_FIRST_NAME}|{USER_TG_LAST_NAME}")
    
    assert result == "123|john_doe|John|Doe"


@pytest.mark.unit
def test_add_message_no_username():
    """Тест: add_message() обрабатывает username=None"""
    resolver = PlaceholderResolver()
    user = TgUser(id=456, username=None, first_name="NoUser", last_name="Name", is_bot=False)
    message = Message(message_id=2, date=datetime.now(), chat=Chat(id=456, type="private"), from_user=user)
    
    resolver.add_message(message)
    result = resolver.resolve("{USER_TG_USERNAME}")
    
    assert result == ""


@pytest.mark.unit
def test_add_message_no_last_name():
    """Тест: add_message() обрабатывает last_name=None"""
    resolver = PlaceholderResolver()
    user = TgUser(id=789, username="single", first_name="Single", last_name=None, is_bot=False)
    message = Message(message_id=3, date=datetime.now(), chat=Chat(id=789, type="private"), from_user=user)
    
    resolver.add_message(message)
    result = resolver.resolve("{USER_TG_LAST_NAME}")
    
    assert result == ""


@pytest.mark.unit
def test_add_message_none_message():
    """Тест: add_message(None) не падает"""
    resolver = PlaceholderResolver()
    
    resolver.add_message(None)
    result = resolver.resolve("{USER_TG_ID}")
    
    assert result == "{USER_TG_ID}"  # Плейсхолдер остался


@pytest.mark.unit
def test_add_message_id_conversion():
    """Тест: ID конвертируется в строку"""
    resolver = PlaceholderResolver()
    user = TgUser(id=999999, username="big_id", first_name="Big", last_name="ID", is_bot=False)
    message = Message(message_id=4, date=datetime.now(), chat=Chat(id=999999, type="private"), from_user=user)
    
    resolver.add_message(message)
    
    assert resolver.context['USER_TG_ID'] == "999999"
    assert isinstance(resolver.context['USER_TG_ID'], str)


# ============================================================================
# B. add_callback() - 4 теста
# ============================================================================

@pytest.mark.unit
def test_add_callback_from_user():
    """Тест: add_callback() извлекает данные из callback.from_user"""
    resolver = PlaceholderResolver()
    user = TgUser(id=111, username="callback_user", first_name="Callback", last_name="User", is_bot=False)
    bot_user = TgUser(id=999, username="bot", first_name="Bot", last_name="", is_bot=True)
    
    message = Message(message_id=5, date=datetime.now(), chat=Chat(id=111, type="private"), from_user=bot_user)
    callback = CallbackQuery(id="cb1", from_user=user, chat_instance="ci", message=message, data="data")
    
    resolver.add_callback(callback)
    result = resolver.resolve("{USER_TG_FIRST_NAME}|{USER_TG_ID}")
    
    assert result == "Callback|111"


@pytest.mark.unit
def test_add_callback_bot_data_not_used():
    """Тест: данные бота из message.from_user НЕ используются"""
    resolver = PlaceholderResolver()
    user = TgUser(id=222, username="real_user", first_name="Real", last_name="User", is_bot=False)
    bot_user = TgUser(id=888, username="bot", first_name="BotName", last_name="BotLast", is_bot=True)
    
    message = Message(message_id=6, date=datetime.now(), chat=Chat(id=222, type="private"), from_user=bot_user)
    callback = CallbackQuery(id="cb2", from_user=user, chat_instance="ci", message=message, data="data")
    
    resolver.add_callback(callback)
    result = resolver.resolve("{USER_TG_FIRST_NAME}")
    
    assert result == "Real"
    assert "BotName" not in result


@pytest.mark.unit
def test_add_callback_no_username():
    """Тест: add_callback() обрабатывает username=None"""
    resolver = PlaceholderResolver()
    user = TgUser(id=333, username=None, first_name="NoUsername", last_name="Test", is_bot=False)
    message = Message(message_id=7, date=datetime.now(), chat=Chat(id=333, type="private"), from_user=user)
    callback = CallbackQuery(id="cb3", from_user=user, chat_instance="ci", message=message, data="data")
    
    resolver.add_callback(callback)
    result = resolver.resolve("{USER_TG_USERNAME}")
    
    assert result == ""


@pytest.mark.unit
def test_add_callback_none_callback():
    """Тест: add_callback(None) не падает"""
    resolver = PlaceholderResolver()
    
    resolver.add_callback(None)
    result = resolver.resolve("{USER_TG_ID}")
    
    assert result == "{USER_TG_ID}"


# ============================================================================
# C. add_user_sub() - 12 тестов
# ============================================================================

@pytest.mark.unit
def test_add_user_sub_status_active():
    """Тест: status = '🟢 Активна' когда is_active=True, is_limited=False"""
    resolver = PlaceholderResolver()
    
    sub_data = {
        'user_sub_id': 1, 'b64_id': 'test123', 'sub_plan_id': 1, 'title': 'Basic',
        'is_active': True, 'is_limited': False,
        'infinite_expire': False, 'expire_date': '2025-12-31T23:59:59.000000+00:00',
        'created_at': '2024-01-01T10:00:00.000000+00:00',
        'infinite_traffic': False, 'traffic_used_day_mb': 100, 'traffic_limit_day': 10240,
        'used_mb': 5000, 'used_mb_limit': 307200, 'sub_nodes_count': 3,
        'offer_prices': []
    }
    user_sub = UserSubSchema.fast_create(sub_data)
    
    resolver.add_user_sub(user_sub)
    result = resolver.resolve("{USER_SUB_STATUS}")
    
    assert result == "🟢 Активна"


@pytest.mark.unit
def test_add_user_sub_status_suspended():
    """Тест: status = '🔴 Приостановлена' когда is_active=False"""
    resolver = PlaceholderResolver()
    
    sub_data = {
        'user_sub_id': 2, 'b64_id': 'test456', 'sub_plan_id': 1, 'title': 'Basic',
        'is_active': False, 'is_limited': False,
        'infinite_expire': False, 'expire_date': '2025-12-31T23:59:59.000000+00:00',
        'created_at': '2024-01-01T10:00:00.000000+00:00',
        'infinite_traffic': False, 'traffic_used_day_mb': 0, 'traffic_limit_day': 10240,
        'used_mb': 0, 'used_mb_limit': 307200, 'sub_nodes_count': 2,
        'offer_prices': []
    }
    user_sub = UserSubSchema.fast_create(sub_data)
    
    resolver.add_user_sub(user_sub)
    result = resolver.resolve("{USER_SUB_STATUS}")
    
    assert result == "🔴 Приостановлена"


@pytest.mark.unit
def test_add_user_sub_status_limited():
    """Тест: status = '🟠 Ограничена' когда is_limited=True (приоритетнее)"""
    resolver = PlaceholderResolver()
    
    sub_data = {
        'user_sub_id': 3, 'b64_id': 'test789', 'sub_plan_id': 1, 'title': 'Basic',
        'is_active': True, 'is_limited': True,  # is_limited приоритетнее
        'infinite_expire': False, 'expire_date': '2025-12-31T23:59:59.000000+00:00',
        'created_at': '2024-01-01T10:00:00.000000+00:00',
        'infinite_traffic': False, 'traffic_used_day_mb': 9000, 'traffic_limit_day': 10240,
        'used_mb': 300000, 'used_mb_limit': 307200, 'sub_nodes_count': 1,
        'offer_prices': []
    }
    user_sub = UserSubSchema.fast_create(sub_data)
    
    resolver.add_user_sub(user_sub)
    result = resolver.resolve("{USER_SUB_STATUS}")
    
    assert result == "🟠 Ограничена"


@pytest.mark.unit
def test_add_user_sub_traffic_limit_day_int():
    """Тест: traffic_limit_day с int значением конвертируется в ГБ (/1024)"""
    resolver = PlaceholderResolver()
    
    sub_data = {
        'user_sub_id': 4, 'b64_id': 'test111', 'sub_plan_id': 1, 'title': 'Basic',
        'is_active': True, 'is_limited': False,
        'infinite_expire': False, 'expire_date': '2025-12-31T23:59:59.000000+00:00',
        'created_at': '2024-01-01T10:00:00.000000+00:00',
        'infinite_traffic': False, 'traffic_used_day_mb': 100,
        'traffic_limit_day': 10240,  # 10 ГБ в МБ
        'used_mb': 5000, 'used_mb_limit': 307200, 'sub_nodes_count': 5,
        'offer_prices': []
    }
    user_sub = UserSubSchema.fast_create(sub_data)
    
    resolver.add_user_sub(user_sub)
    result = resolver.resolve("{USER_SUB_TRAFFIC_LIMIT_DAY}")
    
    assert result == "10"  # 10240 / 1024 = 10 ГБ


@pytest.mark.unit
def test_add_user_sub_traffic_limit_day_none():
    """Тест: traffic_limit_day=None → '-' (прочерк)"""
    resolver = PlaceholderResolver()
    
    sub_data = {
        'user_sub_id': 5, 'b64_id': 'test222', 'sub_plan_id': 1, 'title': 'Basic',
        'is_active': True, 'is_limited': False,
        'infinite_expire': False, 'expire_date': '2025-12-31T23:59:59.000000+00:00',
        'created_at': '2024-01-01T10:00:00.000000+00:00',
        'infinite_traffic': False, 'traffic_used_day_mb': 100,
        'traffic_limit_day': None,  # Нет дневного лимита
        'used_mb': 5000, 'used_mb_limit': 307200, 'sub_nodes_count': 2,
        'offer_prices': []
    }
    user_sub = UserSubSchema.fast_create(sub_data)
    
    resolver.add_user_sub(user_sub)
    result = resolver.resolve("{USER_SUB_TRAFFIC_LIMIT_DAY}")
    
    assert result == "-"


@pytest.mark.unit
def test_add_user_sub_traffic_limit_day_infinite():
    """Тест: traffic_limit_day при infinite_traffic=True → '♾️'"""
    resolver = PlaceholderResolver()
    
    sub_data = {
        'user_sub_id': 6, 'b64_id': 'test333', 'sub_plan_id': 1, 'title': 'Unlimited',
        'is_active': True, 'is_limited': False,
        'infinite_expire': False, 'expire_date': '2025-12-31T23:59:59.000000+00:00',
        'created_at': '2024-01-01T10:00:00.000000+00:00',
        'infinite_traffic': True,  # Безлимитный трафик
        'traffic_used_day_mb': 50000, 'traffic_limit_day': None,
        'used_mb': 500000, 'used_mb_limit': None, 'sub_nodes_count': 10,
        'offer_prices': []
    }
    user_sub = UserSubSchema.fast_create(sub_data)
    
    resolver.add_user_sub(user_sub)
    result = resolver.resolve("{USER_SUB_TRAFFIC_LIMIT_DAY}")
    
    assert result == "♾️"


@pytest.mark.unit
def test_add_user_sub_traffic_limit_int():
    """Тест: traffic_limit с int значением → ГБ"""
    resolver = PlaceholderResolver()
    
    sub_data = {
        'user_sub_id': 7, 'b64_id': 'test444', 'sub_plan_id': 1, 'title': 'Pro',
        'is_active': True, 'is_limited': False,
        'infinite_expire': False, 'expire_date': '2025-12-31T23:59:59.000000+00:00',
        'created_at': '2024-01-01T10:00:00.000000+00:00',
        'infinite_traffic': False, 'traffic_used_day_mb': 100, 'traffic_limit_day': 10240,
        'used_mb': 50000, 'used_mb_limit': 307200,  # 300 ГБ в МБ
        'sub_nodes_count': 7, 'offer_prices': []
    }
    user_sub = UserSubSchema.fast_create(sub_data)
    
    resolver.add_user_sub(user_sub)
    result = resolver.resolve("{USER_SUB_TRAFFIC_LIMIT}")
    
    assert result == "300"  # 307200 / 1024 = 300 ГБ


@pytest.mark.unit
def test_add_user_sub_traffic_limit_none():
    """Тест: traffic_limit=None → '-'"""
    resolver = PlaceholderResolver()
    
    sub_data = {
        'user_sub_id': 8, 'b64_id': 'test555', 'sub_plan_id': 1, 'title': 'Basic',
        'is_active': True, 'is_limited': False,
        'infinite_expire': False, 'expire_date': '2025-12-31T23:59:59.000000+00:00',
        'created_at': '2024-01-01T10:00:00.000000+00:00',
        'infinite_traffic': False, 'traffic_used_day_mb': 100, 'traffic_limit_day': 10240,
        'used_mb': 5000, 'used_mb_limit': None,  # Нет общего лимита
        'sub_nodes_count': 4, 'offer_prices': []
    }
    user_sub = UserSubSchema.fast_create(sub_data)
    
    resolver.add_user_sub(user_sub)
    result = resolver.resolve("{USER_SUB_TRAFFIC_LIMIT}")
    
    assert result == "-"


@pytest.mark.unit
def test_add_user_sub_traffic_limit_infinite():
    """Тест: traffic_limit при infinite_traffic=True → '♾️'"""
    resolver = PlaceholderResolver()
    
    sub_data = {
        'user_sub_id': 9, 'b64_id': 'test666', 'sub_plan_id': 1, 'title': 'Unlimited',
        'is_active': True, 'is_limited': False,
        'infinite_expire': False, 'expire_date': '2025-12-31T23:59:59.000000+00:00',
        'created_at': '2024-01-01T10:00:00.000000+00:00',
        'infinite_traffic': True, 'traffic_used_day_mb': 100, 'traffic_limit_day': None,
        'used_mb': 100000, 'used_mb_limit': None, 'sub_nodes_count': 8,
        'offer_prices': []
    }
    user_sub = UserSubSchema.fast_create(sub_data)
    
    resolver.add_user_sub(user_sub)
    result = resolver.resolve("{USER_SUB_TRAFFIC_LIMIT}")
    
    assert result == "♾️"


@pytest.mark.unit
def test_add_user_sub_expire_date_infinite():
    """Тест: expire_date при infinite_expire=True → '♾️'"""
    resolver = PlaceholderResolver()
    
    sub_data = {
        'user_sub_id': 10, 'b64_id': 'test777', 'sub_plan_id': 1, 'title': 'Lifetime',
        'is_active': True, 'is_limited': False,
        'infinite_expire': True,  # Бессрочная подписка
        'expire_date': '2099-12-31T23:59:59.000000+00:00',  # Будет игнорировано
        'created_at': '2024-01-01T10:00:00.000000+00:00',
        'infinite_traffic': False, 'traffic_used_day_mb': 100, 'traffic_limit_day': 10240,
        'used_mb': 5000, 'used_mb_limit': 307200, 'sub_nodes_count': 12,
        'offer_prices': []
    }
    user_sub = UserSubSchema.fast_create(sub_data)
    
    resolver.add_user_sub(user_sub)
    result = resolver.resolve("{USER_SUB_EXPIRE_DATE}")
    
    assert result == "♾️"


@pytest.mark.unit
def test_add_user_sub_date_formatting():
    """Тест: created_at форматируется в 'DD-MM-YYYY HH:MM'"""
    resolver = PlaceholderResolver()
    
    sub_data = {
        'user_sub_id': 11, 'b64_id': 'test888', 'sub_plan_id': 1, 'title': 'Basic',
        'is_active': True, 'is_limited': False,
        'infinite_expire': False, 'expire_date': '2025-06-15T14:30:00.000000+00:00',
        'created_at': '2024-02-20T09:45:30.000000+00:00',
        'infinite_traffic': False, 'traffic_used_day_mb': 100, 'traffic_limit_day': 10240,
        'used_mb': 5000, 'used_mb_limit': 307200, 'sub_nodes_count': 6,
        'offer_prices': []
    }
    user_sub = UserSubSchema.fast_create(sub_data)
    
    resolver.add_user_sub(user_sub)
    result = resolver.resolve("{USER_SUB_CREATED_AT}")
    
    assert "20-02-2024" in result
    assert "09:45" in result


@pytest.mark.unit
def test_add_user_sub_sub_link_generation():
    """Тест: sub_link генерируется из SUB_SERVICE_URL + b64_id"""
    resolver = PlaceholderResolver()
    
    sub_data = {
        'user_sub_id': 12, 'b64_id': 'test_b64_unique', 'sub_plan_id': 1, 'title': 'Basic',
        'is_active': True, 'is_limited': False,
        'infinite_expire': False, 'expire_date': '2025-12-31T23:59:59.000000+00:00',
        'created_at': '2024-01-01T10:00:00.000000+00:00',
        'infinite_traffic': False, 'traffic_used_day_mb': 100, 'traffic_limit_day': 10240,
        'used_mb': 5000, 'used_mb_limit': 307200, 'sub_nodes_count': 3,
        'offer_prices': []
    }
    user_sub = UserSubSchema.fast_create(sub_data)
    
    resolver.add_user_sub(user_sub)
    result = resolver.resolve("{USER_SUB_LINK}")
    
    assert "test_b64_unique" in result
    assert "/sub/" in result


# ============================================================================
# D. add_shop_plan() - 3 теста
# ============================================================================

@pytest.mark.unit
def test_add_shop_plan_all_fields():
    """Тест: add_shop_plan() извлекает все поля"""
    resolver = PlaceholderResolver()
    
    shop_data = {
        'id': 5,
        'title': 'Premium Plan',
        'description': 'Best plan ever',
        'sub_nodes_count': 15,
        'offer_prices': []
    }
    shop_plan = ShopSubSchema.fast_create(shop_data)
    
    resolver.add_shop_plan(shop_plan)
    result = resolver.resolve("{SUB_ID}|{SUB_TITLE}|{SUB_DESCRIPTION}|{SUB_NODES_COUNT}")
    
    assert result == "5|Premium Plan|Best plan ever|15"


@pytest.mark.unit
def test_add_shop_plan_nodes_count():
    """Тест: sub_nodes_count корректно извлекается"""
    resolver = PlaceholderResolver()
    
    shop_data = {'id': 10, 'title': 'Basic', 'description': 'Desc', 'sub_nodes_count': 7, 'offer_prices': []}
    shop_plan = ShopSubSchema.fast_create(shop_data)
    
    resolver.add_shop_plan(shop_plan)
    
    assert resolver.context['SUB_NODES_COUNT'] == 7
    assert resolver.context['USER_SUB_NODES_COUNT'] == 7


@pytest.mark.unit
def test_add_shop_plan_title_duplication():
    """Тест: SUB_TITLE и USER_SUB_TITLE оба заполняются"""
    resolver = PlaceholderResolver()
    
    shop_data = {'id': 15, 'title': 'Gold', 'description': 'Gold plan', 'sub_nodes_count': 20, 'offer_prices': []}
    shop_plan = ShopSubSchema.fast_create(shop_data)
    
    resolver.add_shop_plan(shop_plan)
    
    assert resolver.context['SUB_TITLE'] == 'Gold'
    assert resolver.context['USER_SUB_TITLE'] == 'Gold'


# ============================================================================
# E. add_price_offer() - 9 тестов
# ============================================================================

@pytest.mark.unit
def test_add_price_offer_traffic_day_int():
    """Тест: traffic_limit_day с int → ГБ (/1024)"""
    resolver = PlaceholderResolver()
    
    offer_data = {
        'offer_id': 1, 'cost': 49900, 'ttl_days': 30,
        'traffic_day_limit': 10240, 'traffic_limit': 307200,
        'infinite_expire': False, 'infinite_traffic': False
    }
    offer = SubOfferSchema.fast_create(offer_data)
    
    resolver.add_price_offer(offer)
    result = resolver.resolve("{SUB_TRAFFIC_LIMIT_DAY}")
    
    assert result == "10"


@pytest.mark.unit
def test_add_price_offer_traffic_day_none():
    """Тест: traffic_limit_day=None → '-'"""
    resolver = PlaceholderResolver()
    
    offer_data = {
        'offer_id': 2, 'cost': 29900, 'ttl_days': 14,
        'traffic_day_limit': None, 'traffic_limit': 51200,
        'infinite_expire': False, 'infinite_traffic': False
    }
    offer = SubOfferSchema.fast_create(offer_data)
    
    resolver.add_price_offer(offer)
    
    assert resolver.context['SUB_TRAFFIC_LIMIT_DAY'] == '-'


@pytest.mark.unit
def test_add_price_offer_traffic_day_infinite():
    """Тест: traffic_limit_day при infinite_traffic=True → '♾️'"""
    resolver = PlaceholderResolver()
    
    offer_data = {
        'offer_id': 3, 'cost': 199900, 'ttl_days': 365,
        'traffic_day_limit': None, 'traffic_limit': None,
        'infinite_expire': False, 'infinite_traffic': True
    }
    offer = SubOfferSchema.fast_create(offer_data)
    
    resolver.add_price_offer(offer)
    
    assert resolver.context['SUB_TRAFFIC_LIMIT_DAY'] == '♾️'


@pytest.mark.unit
def test_add_price_offer_traffic_limit_int():
    """Тест: traffic_limit с int → ГБ"""
    resolver = PlaceholderResolver()
    
    offer_data = {
        'offer_id': 4, 'cost': 79900, 'ttl_days': 60,
        'traffic_day_limit': 15360, 'traffic_limit': 512000,
        'infinite_expire': False, 'infinite_traffic': False
    }
    offer = SubOfferSchema.fast_create(offer_data)
    
    resolver.add_price_offer(offer)
    result = resolver.resolve("{SUB_TRAFFIC_LIMIT}")
    
    assert result == "500"  # 512000 / 1024


@pytest.mark.unit
def test_add_price_offer_traffic_limit_none():
    """Тест: traffic_limit=None → '-'"""
    resolver = PlaceholderResolver()
    
    offer_data = {
        'offer_id': 5, 'cost': 39900, 'ttl_days': 21,
        'traffic_day_limit': 5120, 'traffic_limit': None,
        'infinite_expire': False, 'infinite_traffic': False
    }
    offer = SubOfferSchema.fast_create(offer_data)
    
    resolver.add_price_offer(offer)
    
    assert resolver.context['SUB_TRAFFIC_LIMIT'] == '-'


@pytest.mark.unit
def test_add_price_offer_traffic_limit_infinite():
    """Тест: traffic_limit при infinite_traffic=True → '♾️'"""
    resolver = PlaceholderResolver()
    
    offer_data = {
        'offer_id': 6, 'cost': 299900, 'ttl_days': 730,
        'traffic_day_limit': None, 'traffic_limit': None,
        'infinite_expire': True, 'infinite_traffic': True
    }
    offer = SubOfferSchema.fast_create(offer_data)
    
    resolver.add_price_offer(offer)
    
    assert resolver.context['SUB_TRAFFIC_LIMIT'] == '♾️'


@pytest.mark.unit
def test_add_price_offer_cost_formatting():
    """Тест: cost форматируется с делением на 100 и 2 знаками после запятой"""
    resolver = PlaceholderResolver()
    
    offer_data = {
        'offer_id': 7, 'cost': 12345, 'ttl_days': 7,
        'traffic_day_limit': 1024, 'traffic_limit': 10240,
        'infinite_expire': False, 'infinite_traffic': False
    }
    offer = SubOfferSchema.fast_create(offer_data)
    
    resolver.add_price_offer(offer)
    result = resolver.resolve("{SUB_COST}")
    
    assert " 123.45" in result  # Форматирование с пробелом в начале


@pytest.mark.unit
def test_add_price_offer_ttl_infinite():
    """Тест: ttl_days при infinite_expire=True → '♾️'"""
    resolver = PlaceholderResolver()
    
    offer_data = {
        'offer_id': 8, 'cost': 999900, 'ttl_days': 99999,
        'traffic_day_limit': None, 'traffic_limit': None,
        'infinite_expire': True, 'infinite_traffic': True
    }
    offer = SubOfferSchema.fast_create(offer_data)
    
    resolver.add_price_offer(offer)
    
    assert resolver.context['SUB_TTL_DAYS'] == '♾️'


@pytest.mark.unit
def test_add_price_offer_ttl_days():
    """Тест: ttl_days обычное число остаётся как есть"""
    resolver = PlaceholderResolver()
    
    offer_data = {
        'offer_id': 9, 'cost': 59900, 'ttl_days': 45,
        'traffic_day_limit': 10240, 'traffic_limit': 307200,
        'infinite_expire': False, 'infinite_traffic': False
    }
    offer = SubOfferSchema.fast_create(offer_data)
    
    resolver.add_price_offer(offer)
    
    assert resolver.context['SUB_TTL_DAYS'] == 45


# ============================================================================
# F. add_user() - 2 теста
# ============================================================================

@pytest.mark.unit
def test_add_user_date_formatting():
    """Тест: registered_date форматируется в 'DD-MM-YYYY HH:MM'"""
    resolver = PlaceholderResolver()
    
    user_data = {
        'sub_count': 5,
        'registered_at': '2024-03-15T16:20:45.000000+00:00'
    }
    user = UserSchema.fast_create(user_data)
    
    resolver.add_user(user)
    result = resolver.resolve("{USER_REGISTERED_DATE}")
    
    assert "15-03-2024" in result
    assert "16:20" in result


@pytest.mark.unit
def test_add_user_sub_count():
    """Тест: sub_count корректно извлекается"""
    resolver = PlaceholderResolver()
    
    user_data = {'sub_count': 12, 'registered_at': '2024-01-01T10:00:00.000000+00:00'}
    user = UserSchema.fast_create(user_data)
    
    resolver.add_user(user)
    
    assert resolver.context['USER_SUB_COUNT'] == 12


# ============================================================================
# G. add_custom() - 5 тестов
# ============================================================================

@pytest.mark.unit
def test_add_custom_upper_case():
    """Тест: ключи конвертируются в UPPER_CASE"""
    resolver = PlaceholderResolver()
    
    resolver.add_custom(my_value="test", another_key="data")
    
    assert 'MY_VALUE' in resolver.context
    assert 'ANOTHER_KEY' in resolver.context
    assert 'my_value' not in resolver.context


@pytest.mark.unit
def test_add_custom_none_values():
    """Тест: None конвертируется в пустую строку"""
    resolver = PlaceholderResolver()
    
    resolver.add_custom(empty_field=None, filled_field="data")
    
    assert resolver.context['EMPTY_FIELD'] == ''
    assert resolver.context['FILLED_FIELD'] == 'data'


@pytest.mark.unit
def test_add_custom_type_conversion():
    """Тест: int/float/bool конвертируются в строку"""
    resolver = PlaceholderResolver()
    
    resolver.add_custom(count=42, price=99.99, active=True)
    
    assert resolver.context['COUNT'] == '42'
    assert resolver.context['PRICE'] == '99.99'
    assert resolver.context['ACTIVE'] == 'True'
    assert all(isinstance(v, str) for v in resolver.context.values())


@pytest.mark.unit
def test_add_custom_multiple_values():
    """Тест: несколько кастомных значений одновременно"""
    resolver = PlaceholderResolver()
    
    resolver.add_custom(a="1", b="2", c="3", d="4")
    result = resolver.resolve("{A}-{B}-{C}-{D}")
    
    assert result == "1-2-3-4"


@pytest.mark.unit
def test_add_custom_special_characters():
    """Тест: спецсимволы в значениях сохраняются"""
    resolver = PlaceholderResolver()
    
    resolver.add_custom(emoji="🚀✅", special="@#$%", unicode="Привет")
    result = resolver.resolve("{EMOJI}|{SPECIAL}|{UNICODE}")
    
    assert result == "🚀✅|@#$%|Привет"


# ============================================================================
# H. resolve() - 5 тестов
# ============================================================================

@pytest.mark.unit
def test_resolve_single_placeholder():
    """Тест: resolve() заменяет одиночный плейсхолдер"""
    resolver = PlaceholderResolver()
    resolver.add_custom(name="Alice")
    
    result = resolver.resolve("Hello, {NAME}!")
    
    assert result == "Hello, Alice!"


@pytest.mark.unit
def test_resolve_multiple_placeholders():
    """Тест: resolve() заменяет несколько плейсхолдеров"""
    resolver = PlaceholderResolver()
    resolver.add_custom(first="John", last="Doe", age=30)
    
    result = resolver.resolve("{FIRST} {LAST} is {AGE} years old")
    
    assert result == "John Doe is 30 years old"


@pytest.mark.unit
def test_resolve_unknown_placeholders():
    """Тест: неизвестные плейсхолдеры остаются без изменений"""
    resolver = PlaceholderResolver()
    resolver.add_custom(known="value")
    
    result = resolver.resolve("{KNOWN} and {UNKNOWN}")
    
    assert result == "value and {UNKNOWN}"


@pytest.mark.unit
def test_resolve_empty_template():
    """Тест: resolve() с пустым шаблоном возвращает пустую строку"""
    resolver = PlaceholderResolver()
    resolver.add_custom(test="data")
    
    result = resolver.resolve("")
    
    assert result == ""


@pytest.mark.unit
def test_resolve_no_placeholders():
    """Тест: текст без плейсхолдеров возвращается без изменений"""
    resolver = PlaceholderResolver()
    resolver.add_custom(unused="data")
    
    result = resolver.resolve("Plain text without placeholders")
    
    assert result == "Plain text without placeholders"


# ============================================================================
# I. Fluent API / Chaining - 3 теста
# ============================================================================

@pytest.mark.unit
def test_chaining_multiple_methods():
    """Тест: цепочка вызовов работает корректно"""
    user = TgUser(id=777, username="chain", first_name="Chain", last_name="Test", is_bot=False)
    message = Message(message_id=100, date=datetime.now(), chat=Chat(id=777, type="private"), from_user=user)
    
    result = (
        PlaceholderResolver()
        .add_message(message)
        .add_custom(extra="bonus")
        .resolve("{USER_TG_FIRST_NAME} has {EXTRA}")
    )
    
    assert result == "Chain has bonus"


@pytest.mark.unit
def test_chaining_order_independence():
    """Тест: порядок вызовов не важен (последний перезаписывает)"""
    result1 = PlaceholderResolver().add_custom(val="A").add_custom(val="B").resolve("{VAL}")
    result2 = PlaceholderResolver().add_custom(val="B").add_custom(val="A").resolve("{VAL}")
    
    assert result1 == "B"  # Последнее значение
    assert result2 == "A"


@pytest.mark.unit
def test_chaining_override_values():
    """Тест: повторный вызов метода перезаписывает значения"""
    resolver = PlaceholderResolver()
    resolver.add_custom(key="first")
    resolver.add_custom(key="second")
    
    result = resolver.resolve("{KEY}")
    
    assert result == "second"
