"""
Unit-тесты для функции resolve_user_template

Проверяет подстановку маркеров {USER_UUID} и {USER_SUB_ID}
в шаблоны пользователей для конфигураций протоколов.
"""
import pytest

# ВАЖНО: Отключаем db_seed для unit-тестов (они не требуют БД)
pytestmark = pytest.mark.usefixtures()

from web.arq_worker.funcs.metrics_collector import resolve_user_template


class TestResolveUserTemplate:
    """Тесты функции resolve_user_template"""

    def test_resolve_template_with_uuid_only(self):
        """Подстановка только UUID"""
        template = {"id": "{USER_UUID}"}
        result = resolve_user_template(template, uuid="abc-123")
        
        assert result == {"id": "abc-123"}

    def test_resolve_template_with_username(self):
        """Подстановка UUID и user_sub_id"""
        template = {"email": "{USER_SUB_ID}"}
        result = resolve_user_template(template, uuid="abc-123", user_sub_id=12345)
        
        assert result == {"email": "12345"}  # user_sub_id преобразуется в строку

    def test_resolve_template_with_mixed_fields(self):
        """Подстановка смешанных типов: маркеры + числа + строки"""
        template = {
            "id": "{USER_UUID}",
            "email": "{USER_SUB_ID}",
            "level": 5,
            "alterId": 0
        }
        result = resolve_user_template(
            template, 
            uuid="test-uuid-456", 
            user_sub_id=999
        )
        
        assert result == {
            "id": "test-uuid-456",
            "email": "999",  # user_sub_id преобразуется в строку
            "level": 5,
            "alterId": 0
        }

    def test_resolve_template_with_plain_strings(self):
        """Обычные строковые значения остаются без изменений"""
        template = {
            "custom_field": "static_value",
            "id": "{USER_UUID}",
            "description": "Test user"
        }
        result = resolve_user_template(template, uuid="uuid-789")
        
        assert result == {
            "custom_field": "static_value",
            "id": "uuid-789",
            "description": "Test user"
        }

    def test_resolve_template_with_boolean_and_none(self):
        """Нестроковые типы: boolean, None"""
        template = {
            "id": "{USER_UUID}",
            "is_active": True,
            "suspended": False,
            "extra_data": None
        }
        result = resolve_user_template(template, uuid="uuid-bool")
        
        assert result == {
            "id": "uuid-bool",
            "is_active": True,
            "suspended": False,
            "extra_data": None
        }

    def test_resolve_template_missing_username_raises(self):
        """ValueError если требуется user_sub_id, но он не передан"""
        template = {"email": "{USER_SUB_ID}"}
        
        with pytest.raises(ValueError) as exc_info:
            resolve_user_template(template, uuid="uuid-123", user_sub_id=None)
        
        assert "user_sub_id" in str(exc_info.value)
        assert "USER_SUB_ID" in str(exc_info.value)

    def test_resolve_template_empty_template(self):
        """Пустой шаблон возвращает пустой словарь"""
        template = {}
        result = resolve_user_template(template, uuid="uuid-empty")
        
        assert result == {}

    def test_resolve_template_only_constants(self):
        """Шаблон без маркеров (только константы)"""
        template = {
            "level": 0,
            "protocol": "vless",
            "encryption": "none"
        }
        result = resolve_user_template(template, uuid="uuid-const")
        
        assert result == {
            "level": 0,
            "protocol": "vless",
            "encryption": "none"
        }

    def test_resolve_template_uuid_without_tg_username_ok(self):
        """UUID без username - должно работать"""
        template = {
            "id": "{USER_UUID}",
            "level": 1
        }
        result = resolve_user_template(template, uuid="uuid-no-tg")
        
        assert result == {
            "id": "uuid-no-tg",
            "level": 1
        }

    def test_resolve_template_preserves_nested_structure(self):
        """Сложные вложенные структуры (списки, словари) остаются без изменений"""
        template = {
            "id": "{USER_UUID}",
            "settings": {
                "nested": "value"
            },
            "ports": [8080, 8081]
        }
        result = resolve_user_template(template, uuid="uuid-nested")
        
        assert result == {
            "id": "uuid-nested",
            "settings": {
                "nested": "value"
            },
            "ports": [8080, 8081]
        }

    def test_resolve_template_marker_in_middle_of_string_ignored(self):
        """Маркер в середине строки НЕ заменяется (только точное совпадение)"""
        template = {
            "id": "{USER_UUID}",
            "description": "User {USER_UUID} info"  # Не должно замениться
        }
        result = resolve_user_template(template, uuid="uuid-123")
        
        assert result == {
            "id": "uuid-123",
            "description": "User {USER_UUID} info"  # Осталось как есть
        }

    def test_resolve_template_real_world_vless_example(self):
        """Реальный пример: шаблон для VLESS протокола"""
        template = {
            "id": "{USER_UUID}",
            "email": "{USER_SUB_ID}",
            "level": 0,
            "alterId": 0,
            "flow": "xtls-rprx-vision"
        }
        result = resolve_user_template(
            template,
            uuid="550e8400-e29b-41d4-a716-446655440000",
            user_sub_id=123
        )
        
        assert result == {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "email": "123",  # user_sub_id преобразуется в строку
            "level": 0,
            "alterId": 0,
            "flow": "xtls-rprx-vision"
        }
