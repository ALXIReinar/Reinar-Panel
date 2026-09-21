"""
Unit-тесты для схем валидации виртуальных нод
Тестируют VNodeRegisterSchema и VNodeRegisterResultSchema
"""

import pytest
from pydantic import ValidationError

from web.schemas.nodes_protocols_schema import VNodeRegisterResultSchema, VNodeRegisterSchema


class TestVNodeRegisterSchema:
    """Тесты для схемы регистрации виртуальной ноды"""

    def test_schema_valid_data_full(self):
        """Валидация корректных данных со всеми полями"""
        data = {
            "proto_id": 1,
            "node_id": 2,
            "title": "Test Virtual Node",
            "metrics_port": 9090,
            "proto_port": 8443,
            "config_path": "/etc/vpn/config.json",
            "constant_node_data_obj": {"key": "value"},
            "sub_node_address": "node.example.com",
            "metrics_command": "curl localhost:9999/metrics",
            "reload_core_command": "systemctl reload vpn",
        }

        schema = VNodeRegisterSchema(**data)

        assert schema.tmp_id == 1
        assert schema.node_id == 2
        assert schema.metrics_port == 9090
        assert schema.proto_port == 8443
        assert schema.config_path == "/etc/vpn/config.json"
        assert schema.constant_node_data_obj == {"key": "value"}
        assert schema.sub_node_address == "node.example.com"
        assert schema.metrics_command == "curl localhost:9999/metrics"
        assert schema.reload_core_command == "systemctl reload vpn"

    def test_schema_valid_data_minimal(self):
        """Валидация с минимальными обязательными полями"""
        data = {
            "proto_id": 1,
            "node_id": 2,
            "title": "Minimal Node",
            "proto_port": 8443,
            "config_path": "/etc/vpn/config.json",
        }

        schema = VNodeRegisterSchema(**data)

        assert schema.tmp_id == 1
        assert schema.node_id == 2
        assert schema.proto_port == 8443
        assert schema.config_path == "/etc/vpn/config.json"
        # Опциональные поля должны быть None
        assert schema.metrics_port is None
        assert schema.constant_node_data_obj is None
        assert schema.sub_node_address is None
        assert schema.metrics_command is None
        assert schema.reload_core_command is None

    def test_schema_title_truncation(self):
        """Title обрезается до 27 символов с добавлением '...' если длина > 30"""
        data = {
            "proto_id": 1,
            "node_id": 2,
            "title": "Very Long Title That Should Be Truncated Because It Exceeds Limit",
            "proto_port": 8443,
            "config_path": "/etc/vpn/config.json",
        }

        schema = VNodeRegisterSchema(**data)

        # Ожидаем обрезку до 27 символов + "..."
        assert schema.title == "Very Long Title That Should..."
        assert len(schema.title) == 30  # 27 + 3 символа "..."

    def test_schema_title_short_no_truncation(self):
        """Короткий title (<=30 символов) не обрезается"""
        data = {
            "proto_id": 1,
            "node_id": 2,
            "title": "Short Title",  # 11 символов
            "proto_port": 8443,
            "config_path": "/etc/vpn/config.json",
        }

        schema = VNodeRegisterSchema(**data)

        # Короткий title остаётся без изменений
        assert schema.title == "Short Title"

    def test_schema_title_exactly_30_chars(self):
        """Title ровно 30 символов не обрезается"""
        title_30 = "A" * 30  # Ровно 30 символов
        data = {
            "proto_id": 1,
            "node_id": 2,
            "title": title_30,
            "proto_port": 8443,
            "config_path": "/etc/vpn/config.json",
        }

        schema = VNodeRegisterSchema(**data)

        assert schema.title == title_30
        assert len(schema.title) == 30

    def test_schema_equal_ports_validation(self):
        """Валидация: metrics_port == proto_port должна вызывать ошибку"""
        data = {
            "proto_id": 1,
            "node_id": 2,
            "title": "Equal Ports Node",
            "metrics_port": 8443,
            "proto_port": 8443,  # Тот же порт
            "config_path": "/etc/vpn/config.json",
        }

        with pytest.raises(ValidationError) as exc_info:
            VNodeRegisterSchema(**data)

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("proto_port",)
        assert "не могут быть равны" in errors[0]["msg"]

    def test_schema_port_range_proto_port_too_low(self):
        """proto_port должен быть > 0"""
        data = {
            "proto_id": 1,
            "node_id": 2,
            "title": "Invalid Port",
            "proto_port": 0,  # Недопустимый порт
            "config_path": "/etc/vpn/config.json",
        }

        with pytest.raises(ValidationError) as exc_info:
            VNodeRegisterSchema(**data)

        errors = exc_info.value.errors()
        assert any("greater than 0" in str(err["msg"]) for err in errors)

    def test_schema_port_range_proto_port_too_high(self):
        """proto_port должен быть <= 65535"""
        data = {
            "proto_id": 1,
            "node_id": 2,
            "title": "Invalid Port",
            "proto_port": 70000,  # Недопустимый порт
            "config_path": "/etc/vpn/config.json",
        }

        with pytest.raises(ValidationError) as exc_info:
            VNodeRegisterSchema(**data)

        errors = exc_info.value.errors()
        assert any("less than or equal to 65535" in str(err["msg"]) for err in errors)

    def test_schema_port_range_metrics_port_too_low(self):
        """metrics_port должен быть > 0 (если указан)"""
        data = {
            "proto_id": 1,
            "node_id": 2,
            "title": "Invalid Metrics Port",
            "metrics_port": 0,
            "proto_port": 8443,
            "config_path": "/etc/vpn/config.json",
        }

        with pytest.raises(ValidationError) as exc_info:
            VNodeRegisterSchema(**data)

        errors = exc_info.value.errors()
        # Проверяем что ошибка связана с metrics_port
        assert any(err["loc"][0] == "metrics_port" for err in errors)

    def test_schema_port_range_metrics_port_too_high(self):
        """metrics_port должен быть <= 65535"""
        data = {
            "proto_id": 1,
            "node_id": 2,
            "title": "Invalid Metrics Port",
            "metrics_port": 99999,
            "proto_port": 8443,
            "config_path": "/etc/vpn/config.json",
        }

        with pytest.raises(ValidationError) as exc_info:
            VNodeRegisterSchema(**data)

        errors = exc_info.value.errors()
        # Проверяем что ошибка связана с metrics_port
        assert any(err["loc"][0] == "metrics_port" for err in errors)

    def test_schema_missing_required_fields(self):
        """Отсутствие обязательных полей должно вызывать ошибку"""
        data = {
            "proto_id": 1,
            # Отсутствуют node_id, title, proto_port, config_path
        }

        with pytest.raises(ValidationError) as exc_info:
            VNodeRegisterSchema(**data)

        errors = exc_info.value.errors()
        missing_fields = {err["loc"][0] for err in errors}
        assert "node_id" in missing_fields
        assert "title" in missing_fields
        assert "proto_port" in missing_fields
        assert "config_path" in missing_fields

    def test_schema_constant_node_data_obj_dict(self):
        """constant_node_data_obj принимает dict"""
        data = {
            "proto_id": 1,
            "node_id": 2,
            "title": "Node with Data",
            "proto_port": 8443,
            "config_path": "/etc/vpn/config.json",
            "constant_node_data_obj": {"nested": {"key": "value"}, "array": [1, 2, 3]},
        }

        schema = VNodeRegisterSchema(**data)

        assert schema.constant_node_data_obj == {"nested": {"key": "value"}, "array": [1, 2, 3]}

    def test_schema_constant_node_data_obj_none(self):
        """constant_node_data_obj может быть None"""
        data = {
            "proto_id": 1,
            "node_id": 2,
            "title": "Node without Data",
            "proto_port": 8443,
            "config_path": "/etc/vpn/config.json",
            "constant_node_data_obj": None,
        }

        schema = VNodeRegisterSchema(**data)

        assert schema.constant_node_data_obj is None


class TestVNodeRegisterResultSchema:
    """Тесты для схемы результата регистрации (confirm)"""

    def test_schema_valid_data_success_status(self):
        """Валидация с status=2 (success)"""
        data = {
            "node_proto_id": 123,
            "status": 2,
            "title": "Confirmed Node",  # 14 символов - короткий title
            "constant_node_data_obj": {"confirmed": True},
            "reload_core_command": "systemctl reload",
            "metrics_command": "curl metrics",
            "config_path": "/etc/vpn/confirmed.json",
        }

        schema = VNodeRegisterResultSchema(**data)

        assert schema.node_proto_id == 123
        assert schema.status == 2
        assert schema.title == "Confirmed Node"  # Короткий title не обрезается
        assert schema.constant_node_data_obj == {"confirmed": True}
        assert schema.reload_core_command == "systemctl reload"
        assert schema.metrics_command == "curl metrics"
        assert schema.config_path == "/etc/vpn/confirmed.json"

    def test_schema_valid_data_failed_status(self):
        """Валидация с status=3 (failed)"""
        data = {
            "node_proto_id": 456,
            "status": 3,
        }

        schema = VNodeRegisterResultSchema(**data)

        assert schema.node_proto_id == 456
        assert schema.status == 3

    def test_schema_string_status_success(self):
        """Преобразование строки "success" в int 2"""
        data = {
            "node_proto_id": 789,
            "status": "success",
        }

        schema = VNodeRegisterResultSchema(**data)

        assert schema.status == 2

    def test_schema_string_status_failed(self):
        """Преобразование строки "failed" в int 3"""
        data = {
            "node_proto_id": 790,
            "status": "failed",
        }

        schema = VNodeRegisterResultSchema(**data)

        assert schema.status == 3

    def test_schema_string_status_case_insensitive(self):
        """Строковый статус case-insensitive"""
        data_upper = {
            "node_proto_id": 791,
            "status": "SUCCESS",
        }

        schema_upper = VNodeRegisterResultSchema(**data_upper)
        assert schema_upper.status == 2

        data_mixed = {
            "node_proto_id": 792,
            "status": "FaIlEd",
        }

        schema_mixed = VNodeRegisterResultSchema(**data_mixed)
        assert schema_mixed.status == 3

    def test_schema_invalid_status_value(self):
        """Недопустимое значение статуса (не в диапазоне 1-3)"""
        data = {
            "node_proto_id": 793,
            "status": 5,  # Недопустимый статус
        }

        with pytest.raises(ValidationError) as exc_info:
            VNodeRegisterResultSchema(**data)

        errors = exc_info.value.errors()
        assert any("вне диапазона 1-3" in str(err["msg"]) for err in errors)

    def test_schema_invalid_string_status(self):
        """Недопустимая строка статуса"""
        data = {
            "node_proto_id": 794,
            "status": "unknown",  # Недопустимая строка
        }

        with pytest.raises(ValidationError) as exc_info:
            VNodeRegisterResultSchema(**data)

        errors = exc_info.value.errors()
        # Схема должна отклонить неизвестную строку
        assert len(errors) > 0

    def test_schema_title_truncation(self):
        """Title обрезается до 27 символов + '...' если длина > 30"""
        data = {
            "node_proto_id": 795,
            "status": 2,
            "title": "Another Very Long Title That Should Be Truncated",
        }

        schema = VNodeRegisterResultSchema(**data)

        assert schema.title == "Another Very Long Title Tha..."
        assert len(schema.title) == 30

    def test_schema_title_short_no_truncation(self):
        """Title короче или равный 30 символам не обрезается"""
        data = {
            "node_proto_id": 795,
            "status": 2,
            "title": "Short Title",
        }

        schema = VNodeRegisterResultSchema(**data)

        assert schema.title == "Short Title"

    def test_schema_title_none(self):
        """Title может быть None"""
        data = {
            "node_proto_id": 796,
            "status": 2,
            "title": None,
        }

        schema = VNodeRegisterResultSchema(**data)

        assert schema.title is None

    def test_schema_constant_node_data_obj_zero(self):
        """constant_node_data_obj может быть 0 (специальное значение)"""
        data = {
            "node_proto_id": 797,
            "status": 2,
            "constant_node_data_obj": 0,
        }

        schema = VNodeRegisterResultSchema(**data)

        assert schema.constant_node_data_obj == 0

    def test_schema_constant_node_data_obj_dict(self):
        """constant_node_data_obj может быть dict"""
        data = {
            "node_proto_id": 798,
            "status": 2,
            "constant_node_data_obj": {"result": "confirmed"},
        }

        schema = VNodeRegisterResultSchema(**data)

        assert schema.constant_node_data_obj == {"result": "confirmed"}

    def test_schema_constant_node_data_obj_none(self):
        """constant_node_data_obj может быть None"""
        data = {
            "node_proto_id": 799,
            "status": 2,
            "constant_node_data_obj": None,
        }

        schema = VNodeRegisterResultSchema(**data)

        assert schema.constant_node_data_obj is None

    def test_schema_minimal_required_fields(self):
        """Минимальный набор обязательных полей"""
        data = {
            "node_proto_id": 800,
            "status": 2,
        }

        schema = VNodeRegisterResultSchema(**data)

        assert schema.node_proto_id == 800
        assert schema.status == 2
        # Все остальные поля должны иметь дефолтные значения
        assert schema.title is None
        assert schema.constant_node_data_obj == 0  # Дефолт
        assert schema.reload_core_command is None
        assert schema.metrics_command is None
        assert schema.config_path is None

    def test_schema_missing_required_node_proto_id(self):
        """Отсутствие node_proto_id должно вызывать ошибку"""
        data = {
            "status": 2,
        }

        with pytest.raises(ValidationError) as exc_info:
            VNodeRegisterResultSchema(**data)

        errors = exc_info.value.errors()
        assert any(err["loc"][0] == "node_proto_id" for err in errors)

    def test_schema_missing_required_status(self):
        """Отсутствие status должно вызывать ошибку"""
        data = {
            "node_proto_id": 801,
        }

        with pytest.raises(ValidationError) as exc_info:
            VNodeRegisterResultSchema(**data)

        errors = exc_info.value.errors()
        assert any(err["loc"][0] == "status" for err in errors)
