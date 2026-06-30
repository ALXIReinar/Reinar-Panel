"""
Тесты для универсального парсера метрик Xray из БД

Парсер загружается из proto_templates.metrics_parser_code (реальный шаблон)
через фикстуру ... (определена в conftest.py)

Парсер должен обрабатывать:
1. JSON string (от CLI xray api statsquery)
2. JSON dict (от xtlsapi.XrayClient.stats_query())
3. Plain text (fallback для legacy)
"""
import pytest


# ========== Тесты для JSON формата (от CLI) ==========

@pytest.mark.db
def test_parse_json_string_from_cli():
    """Парсинг JSON строки от xray api statsquery"""
    parse = ...
    
    json_string = '''
    {
        "stat": [
            {"name": "user>>>test@email.com>>>traffic>>>downlink", "value": 1073741824},
            {"name": "user>>>test@email.com>>>traffic>>>uplink", "value": 536870912},
            {"name": "user>>>user2@test.com>>>traffic>>>downlink", "value": 2147483648}
        ]
    }
    '''
    
    users_traffics, troubles = parse(json_string)
    
    assert len(users_traffics) == 2
    assert len(troubles) == 0
    
    user1 = next(u for u in users_traffics if u['tg_username'] == 'test@email.com')
    assert user1['total_mb_used'] == 1024 + 512
    
    user2 = next(u for u in users_traffics if u['tg_username'] == 'user2@test.com')
    assert user2['total_mb_used'] == 2048


@pytest.mark.db
def test_parse_json_dict_from_xtlsapi(...):
    """Парсинг JSON dict от xtlsapi.XrayClient"""
    parse = ...
    
    json_dict = {
        "stat": [
            {"name": "user>>>admin@test.com>>>traffic>>>downlink", "value": 5368709120},
            {"name": "user>>>admin@test.com>>>traffic>>>uplink", "value": 1073741824}
        ]
    }
    
    users_traffics, troubles = parse(json_dict)
    
    assert len(users_traffics) == 1
    user = users_traffics[0]
    assert user['tg_username'] == 'admin@test.com'
    assert user['total_mb_used'] == 5120 + 1024


@pytest.mark.db
def test_parse_empty_stats(...):
    """Обработка пустого списка статистики"""
    parse = ...
    
    json_dict = {"stat": []}
    users_traffics, troubles = parse(json_dict)
    
    assert len(users_traffics) == 0
    assert len(troubles) == 0


@pytest.mark.db
def test_parse_missing_stat_key(...):
    """Обработка JSON без ключа 'stat'"""
    parse = ...
    
    json_dict = {"other_key": "value"}
    users_traffics, troubles = parse(json_dict)
    
    assert len(users_traffics) == 0
    assert len(troubles) == 0


# ========== Тесты для некорректных данных ==========

@pytest.mark.db
def test_parse_invalid_name_format(...):
    """Обработка некорректного формата имени"""
    parse = ...
    
    json_dict = {
        "stat": [
            {"name": "invalid_format_without_separators", "value": 1024},
            {"name": "user>>>valid@test.com>>>traffic>>>downlink", "value": 2048}
        ]
    }
    
    users_traffics, troubles = parse(json_dict)
    
    assert len(users_traffics) == 1
    assert len(troubles) == 1
    assert troubles[0]['name'] == 'invalid_format_without_separators'


@pytest.mark.db
def test_parse_missing_name_key(...):
    """Обработка записей без ключа 'name'"""
    parse = ...
    
    json_dict = {
        "stat": [
            {"value": 1024},
            {"name": "user>>>test@test.com>>>traffic>>>uplink", "value": 512}
        ]
    }
    
    users_traffics, troubles = parse(json_dict)
    
    assert len(users_traffics) == 1
    assert len(troubles) == 1


@pytest.mark.db
def test_parse_zero_traffic(...):
    """Обработка нулевого трафика"""
    parse = ...
    
    json_dict = {
        "stat": [
            {"name": "user>>>zero@test.com>>>traffic>>>downlink", "value": 0}
        ]
    }
    
    users_traffics, troubles = parse(json_dict)
    
    assert len(users_traffics) == 1
    assert users_traffics[0]['total_mb_used'] == 0


# ========== Тесты для Plain text fallback ==========

@pytest.mark.db
def test_parse_plain_text_fallback(...):
    """Fallback на plain text парсинг"""
    parse = ...
    
    plain_text = """
    user>>>test@email>>>uplink: 1024
    user>>>test@email>>>downlink: 2048
    user>>>user2>>>uplink: 512
    """
    
    users_traffics, troubles = parse(plain_text)
    
    assert isinstance(users_traffics, list)
    assert isinstance(troubles, list)


@pytest.mark.db
def test_parse_invalid_json_fallback_to_plain(...):
    """При некорректном JSON переключается на plain text"""
    parse = ...
    
    invalid_json = "{invalid json syntax [,]}"
    users_traffics, troubles = parse(invalid_json)
    
    assert isinstance(users_traffics, list)
    assert isinstance(troubles, list)


# ========== Тесты для агрегации трафика ==========

@pytest.mark.db
def test_aggregate_traffic_for_same_user(...):
    """Агрегация трафика для одного пользователя (uplink + downlink)"""
    parse = ...
    
    json_dict = {
        "stat": [
            {"name": "user>>>test@test.com>>>traffic>>>uplink", "value": 1073741824},
            {"name": "user>>>test@test.com>>>traffic>>>downlink", "value": 2147483648},
            {"name": "user>>>test@test.com>>>traffic>>>uplink", "value": 536870912}
        ]
    }
    
    users_traffics, troubles = parse(json_dict)
    
    assert len(users_traffics) == 1
    user = users_traffics[0]
    assert user['tg_username'] == 'test@test.com'
    assert user['total_mb_used'] == 1024 + 2048 + 512


@pytest.mark.db
def test_multiple_users_traffic(...):
    """Парсинг трафика для нескольких пользователей"""
    parse = ...
    
    json_dict = {
        "stat": [
            {"name": "user>>>alice@test.com>>>traffic>>>downlink", "value": 1073741824},
            {"name": "user>>>bob@test.com>>>traffic>>>uplink", "value": 536870912},
            {"name": "user>>>charlie@test.com>>>traffic>>>downlink", "value": 2147483648}
        ]
    }
    
    users_traffics, troubles = parse(json_dict)
    
    assert len(users_traffics) == 3
    
    usernames = {u['tg_username'] for u in users_traffics}
    assert usernames == {'alice@test.com', 'bob@test.com', 'charlie@test.com'}


# ========== Тесты для граничных случаев ==========

@pytest.mark.db
def test_parse_very_large_traffic(...):
    """Обработка очень больших значений трафика"""
    parse = ...
    
    json_dict = {
        "stat": [
            {"name": "user>>>heavy@user.com>>>traffic>>>downlink", "value": 1099511627776}
        ]
    }
    
    users_traffics, troubles = parse(json_dict)
    
    assert len(users_traffics) == 1
    assert users_traffics[0]['total_mb_used'] == 1024 * 1024


@pytest.mark.db
def test_parse_string_value_converted_to_int(...):
    """value как строка должна конвертироваться в int"""
    parse = ...
    
    json_dict = {
        "stat": [
            {"name": "user>>>test@test.com>>>traffic>>>downlink", "value": "1073741824"}
        ]
    }
    
    users_traffics, troubles = parse(json_dict)
    
    assert len(users_traffics) == 1
    assert users_traffics[0]['total_mb_used'] == 1024
