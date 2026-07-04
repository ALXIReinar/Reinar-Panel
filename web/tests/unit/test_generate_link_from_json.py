"""
Юнит-тесты для функции generate_link_from_json
Тестируют генерацию конфиг-ссылок VLESS из JSON конфига
"""
import json
import pytest
from web.api.protocols.proto_links_templates.handlers import generate_link_from_json


@pytest.fixture
def vless_config():
    """Загружаем реальный конфиг-файл VLESS с TCP"""
    with open("web/tests/utils/vless-tcp-server-metrics-copy.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def vless_template():
    """Шаблон ссылки для VLESS Reality"""
    return (
        "vless://{user_uuid}@{{node___address}}:{{inbounds___1___port}}?"
        "encryption=none&flow={{flow}}&security={{inbounds___1___streamSettings___security}}&"
        "sni={{inbounds___1___streamSettings___realitySettings___serverNames___0}}&"
        "fp={{inbounds___1___streamSettings___realitySettings___fingerprint}}&"
        "pbk={{pbk}}&"
        "sid={{inbounds___1___streamSettings___realitySettings___shortIds___1}}&"
        "type={{inbounds___1___streamSettings___network}}#{{node___title}}"
    )


@pytest.fixture
def spec_params():
    """Кастомные параметры, которых нет в конфиг-файле"""
    return {
        "pbk": "ANY_PBK_VALUE",
        "flow": "test-xtls"
    }


class TestGenerateLinkSuccess:
    """Тесты успешной генерации ссылки"""
    
    def test_generate_link_with_dict_config(self, vless_config, vless_template, spec_params):
        """Генерация ссылки с конфигом в виде словаря"""
        success, result = generate_link_from_json(
            tmp_link=vless_template,
            node_config_json=vless_config,  # dict
            spec_keys_values=spec_params,
            node_ip_or_domain="192.168.1.100",
            node_title="TestNode RU"
        )
        
        assert success is True
        assert result.startswith("vless://{user_uuid}@192.168.1.100:443?")
        assert "encryption=none" in result
        assert "flow=test-xtls" in result
        assert "security=reality" in result
        assert "sni=www.microsoft.com" in result
        assert "fp=chrome" in result
        assert "pbk=ANY_PBK_VALUE" in result
        assert "sid=709c400f8da05ef4" in result
        assert "type=raw" in result
        assert result.endswith("#TestNode%20RU")  # URL-encoded пробел
    
    def test_generate_link_with_string_config(self, vless_config, vless_template, spec_params):
        """Генерация ссылки с конфигом в виде JSON строки"""
        config_str = json.dumps(vless_config)
        
        success, result = generate_link_from_json(
            tmp_link=vless_template,
            node_config_json=config_str,  # string
            spec_keys_values=spec_params,
            node_ip_or_domain="example.com",
            node_title="My Server"
        )
        
        assert success is True
        assert "vless://{user_uuid}@example.com:443" in result
        assert "pbk=ANY_PBK_VALUE" in result
    
    def test_generate_link_with_domain(self, vless_config, vless_template, spec_params):
        """Генерация ссылки с доменом вместо IP"""
        success, result = generate_link_from_json(
            tmp_link=vless_template,
            node_config_json=vless_config,
            spec_keys_values=spec_params,
            node_ip_or_domain="vpn.example.com",
            node_title="VPN Node"
        )
        
        assert success is True
        assert "@vpn.example.com:443" in result
    
    def test_generate_link_title_encoding(self, vless_config, vless_template, spec_params):
        """URL-encoding названия ноды с кириллицей и спецсимволами"""
        success, result = generate_link_from_json(
            tmp_link=vless_template,
            node_config_json=vless_config,
            spec_keys_values=spec_params,
            node_ip_or_domain="1.2.3.4",
            node_title="Москва 🇷🇺 #1"
        )
        
        assert success is True
        # Проверяем что название закодировано (quote)
        assert result.endswith("#%D0%9C%D0%BE%D1%81%D0%BA%D0%B2%D0%B0%20%F0%9F%87%B7%F0%9F%87%BA%20%231")
    
    def test_generate_link_flatten_nested_keys(self, vless_config, vless_template, spec_params):
        """Проверка что вложенные ключи правильно обрабатываются через flatten"""
        success, result = generate_link_from_json(
            tmp_link=vless_template,
            node_config_json=vless_config,
            spec_keys_values=spec_params,
            node_ip_or_domain="10.0.0.1",
            node_title="Node"
        )
        
        assert success is True
        # Проверяем глубоко вложенные ключи из конфига
        assert "sni=www.microsoft.com" in result  # inbounds[1].streamSettings.realitySettings.serverNames[0]
        assert "fp=chrome" in result  # inbounds[1].streamSettings.realitySettings.fingerprint
        assert "sid=709c400f8da05ef4" in result  # inbounds[1].streamSettings.realitySettings.shortIds[1]


class TestGenerateLinkErrors:
    """Тесты ошибочных сценариев"""
    
    def test_generate_link_no_template(self, vless_config, spec_params):
        """Шаблон ссылки не указан (None)"""
        success, error_msg = generate_link_from_json(
            tmp_link=None,
            node_config_json=vless_config,
            spec_keys_values=spec_params,
            node_ip_or_domain="1.2.3.4",
            node_title="Node"
        )
        
        assert success is False
        assert "не указана" in error_msg
        assert "шаблон" in error_msg.lower()
    
    def test_generate_link_missing_spec_key_in_template(self, vless_config, vless_template):
        """Spec ключ указан в параметрах, но отсутствует в шаблоне"""
        # Добавляем ключ, которого нет в шаблоне
        spec_params_with_extra = {
            "pbk": "ANY_PBK_VALUE",
            "flow": "test-xtls",
            "extra_key": "should_be_in_template"  # Этого ключа нет в шаблоне!
        }
        
        success, error_msg = generate_link_from_json(
            tmp_link=vless_template,
            node_config_json=vless_config,
            spec_keys_values=spec_params_with_extra,
            node_ip_or_domain="1.2.3.4",
            node_title="Node"
        )
        
        assert success is False
        assert "extra_key" in error_msg
        assert "отсутствует в ссылке-шаблоне" in error_msg
    
    def test_generate_link_invalid_json_string(self, vless_template, spec_params):
        """Некорректная JSON строка в конфиге"""
        invalid_json = '{"invalid": json}'
        
        with pytest.raises(json.JSONDecodeError):
            generate_link_from_json(
                tmp_link=vless_template,
                node_config_json=invalid_json,
                spec_keys_values=spec_params,
                node_ip_or_domain="1.2.3.4",
                node_title="Node"
            )


class TestGenerateLinkEdgeCases:
    """Тесты граничных случаев"""
    
    def test_generate_link_empty_spec_params(self, vless_config):
        """Генерация ссылки без кастомных параметров"""
        # Простой шаблон без spec параметров
        simple_template = "vless://{user_uuid}@{{node___address}}:{{inbounds___1___port}}#{{node___title}}"
        
        success, result = generate_link_from_json(
            tmp_link=simple_template,
            node_config_json=vless_config,
            spec_keys_values={},  # Пустые spec параметры
            node_ip_or_domain="1.2.3.4",
            node_title="Node"
        )
        
        assert success is True
        assert "vless://{user_uuid}@1.2.3.4:443#Node" == result
    
    def test_generate_link_spec_key_with_underscores(self, vless_config):
        """Spec ключ с подчёркиваниями не конфликтует с flatten separator"""
        template_with_underscores = (
            "vless://{user_uuid}@{{node___address}}:{{inbounds___1___port}}?"
            "custom={{my_custom_key}}#{{node___title}}"
        )
        spec_params = {"my_custom_key": "value_with_underscores"}
        
        success, result = generate_link_from_json(
            tmp_link=template_with_underscores,
            node_config_json=vless_config,
            spec_keys_values=spec_params,
            node_ip_or_domain="1.2.3.4",
            node_title="Node"
        )
        
        assert success is True
        assert "custom=value_with_underscores" in result
    
    def test_generate_link_empty_title(self, vless_config, vless_template, spec_params):
        """Пустое название ноды"""
        success, result = generate_link_from_json(
            tmp_link=vless_template,
            node_config_json=vless_config,
            spec_keys_values=spec_params,
            node_ip_or_domain="1.2.3.4",
            node_title=""  # Пустое название
        )
        
        assert success is True
        assert result.endswith("#")  # Хештег присутствует, но после него пусто
    
    def test_generate_link_ipv6_address(self, vless_config, vless_template, spec_params):
        """Использование IPv6 адреса"""
        success, result = generate_link_from_json(
            tmp_link=vless_template,
            node_config_json=vless_config,
            spec_keys_values=spec_params,
            node_ip_or_domain="2001:db8::1",
            node_title="IPv6 Node"
        )
        
        assert success is True
        assert "@2001:db8::1:443" in result


class TestGenerateLinkSystemFields:
    """Тесты системных полей (node___address, node___title)"""
    
    def test_system_fields_override_config(self, vless_template, spec_params):
        """Системные поля node___address и node___title переопределяют значения из конфига"""
        # Конфиг с полями, которые могут конфликтовать
        config_with_node_fields = {
            "node___address": "should_be_overridden",
            "node___title": "should_be_overridden",
            "inbounds": [
                {"port": 10085, "protocol": "dokodemo-door"},
                {
                    "port": 443,
                    "protocol": "vless",
                    "streamSettings": {
                        "network": "tcp",
                        "security": "reality",
                        "realitySettings": {
                            "fingerprint": "chrome",
                            "serverNames": ["example.com"],
                            "shortIds": ["", "abc123"]
                        }
                    }
                }
            ]
        }
        
        success, result = generate_link_from_json(
            tmp_link=vless_template,
            node_config_json=config_with_node_fields,
            spec_keys_values=spec_params,
            node_ip_or_domain="real_address.com",  # Должно использоваться это
            node_title="Real Title"  # Должно использоваться это
        )
        
        assert success is True
        assert "@real_address.com:443" in result
        assert result.endswith("#Real%20Title")
        # Проверяем что значения из конфига НЕ использовались
        assert "should_be_overridden" not in result
