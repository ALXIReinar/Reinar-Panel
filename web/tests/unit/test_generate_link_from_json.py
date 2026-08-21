"""
Юнит-тесты для функции generate_link_from_json
Тестируют механику генерации конфиг-ссылок: flatten JSON, Jinja2 подстановка, URL encoding

NOTE: Эти тесты проверяют LOW-LEVEL механику функции, а не конкретные шаблоны.
Проверка реальных шаблонов из БД выполняется в integration тестах test_sub_prepare_scripts.py
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
    """
    Шаблон ссылки для VLESS Reality (теперь с позиции 0, т.к. порядок inbounds изменён)
    
    Одинарные плейсхолдеры {user_uuid}, {flow}, {fp}, {pbk} НЕ подставляются здесь - 
    это задача prepare_sub скриптов
    """
    return (
        "vless://{user_uuid}@{{node___address}}:{{inbounds___0___port}}?"
        "encryption=none&flow={flow}&security={{inbounds___0___streamSettings___security}}&"
        "sni={{inbounds___0___streamSettings___realitySettings___serverNames___0}}&"
        "fp={fp}&pbk={pbk}&"
        "sid={{inbounds___0___streamSettings___realitySettings___shortIds___1}}&"
        "type={{inbounds___0___streamSettings___network}}#{{node___title}}"
    )


class TestGenerateLinkSuccess:
    """Тесты успешной генерации ссылки"""
    
    def test_generate_link_with_dict_config(self, vless_config, vless_template):
        """Генерация ссылки с конфигом в виде словаря"""
        success, result = generate_link_from_json(
            tmp_link=vless_template,
            node_config_json=vless_config,  # dict
            node_ip_or_domain="192.168.1.100",
            node_title="TestNode RU"
        )
        
        assert success is True
        assert result.startswith("vless://{user_uuid}@192.168.1.100:443?")
        assert "encryption=none" in result
        # Одинарные плейсхолдеры остались как есть (подставятся в prepare_sub)
        assert "flow={flow}" in result
        assert "fp={fp}" in result
        assert "pbk={pbk}" in result
        # Двойные плейсхолдеры подставились из конфига
        assert "security=reality" in result
        assert "sni=www.microsoft.com" in result
        assert "sid=709c400f8da05ef4" in result
        assert "type=raw" in result
        assert result.endswith("#TestNode%20RU")  # URL-encoded пробел
    
    def test_generate_link_with_string_config(self, vless_config, vless_template):
        """Генерация ссылки с конфигом в виде JSON строки"""
        config_str = json.dumps(vless_config)
        
        success, result = generate_link_from_json(
            tmp_link=vless_template,
            node_config_json=config_str,  # string
            node_ip_or_domain="example.com",
            node_title="My Server"
        )
        
        assert success is True
        assert "vless://{user_uuid}@example.com:443" in result
        # Двойные плейсхолдеры подставились
        assert "security=reality" in result
        # Одинарные остались
        assert "{user_uuid}" in result
        assert "{flow}" in result
    
    def test_generate_link_with_domain(self, vless_config, vless_template):
        """Генерация ссылки с доменом вместо IP"""
        success, result = generate_link_from_json(
            tmp_link=vless_template,
            node_config_json=vless_config,
            node_ip_or_domain="vpn.example.com",
            node_title="VPN Node"
        )
        
        assert success is True
        assert "@vpn.example.com:443" in result
    
    def test_generate_link_title_encoding(self, vless_config, vless_template):
        """URL-encoding названия ноды с кириллицей и спецсимволами"""
        success, result = generate_link_from_json(
            tmp_link=vless_template,
            node_config_json=vless_config,
            node_ip_or_domain="1.2.3.4",
            node_title="Москва 🇷🇺 #1"
        )
        
        assert success is True
        # Проверяем что название закодировано (quote)
        assert result.endswith("#%D0%9C%D0%BE%D1%81%D0%BA%D0%B2%D0%B0%20%F0%9F%87%B7%F0%9F%87%BA%20%231")
    
    def test_generate_link_flatten_nested_keys(self, vless_config, vless_template):
        """Проверка что вложенные ключи правильно обрабатываются через flatten"""
        success, result = generate_link_from_json(
            tmp_link=vless_template,
            node_config_json=vless_config,
            node_ip_or_domain="10.0.0.1",
            node_title="Node"
        )
        
        assert success is True
        # Проверяем глубоко вложенные ключи из конфига (с позиции 0 теперь)
        assert "sni=www.microsoft.com" in result  # inbounds[0].streamSettings.realitySettings.serverNames[0]
        assert "sid=709c400f8da05ef4" in result  # inbounds[0].streamSettings.realitySettings.shortIds[1]
        # Проверяем что двойные плейсхолдеры исчезли
        assert "{{" not in result
        assert "}}" not in result


class TestGenerateLinkErrors:
    """Тесты ошибочных сценариев"""
    
    def test_generate_link_no_template(self, vless_config):
        """Шаблон ссылки не указан (None)"""
        success, error_msg = generate_link_from_json(
            tmp_link=None,
            node_config_json=vless_config,
            node_ip_or_domain="1.2.3.4",
            node_title="Node"
        )
        
        assert success is False
        assert "не указана" in error_msg
        assert "шаблон" in error_msg.lower() or "url" in error_msg.lower()
    
    def test_generate_link_empty_template(self, vless_config):
        """Пустая строка в качестве шаблона"""
        success, error_msg = generate_link_from_json(
            tmp_link="",
            node_config_json=vless_config,
            node_ip_or_domain="1.2.3.4",
            node_title="Node"
        )
        
        assert success is False
        assert "не указана" in error_msg
    
    def test_generate_link_invalid_json_string(self, vless_template):
        """Некорректная JSON строка в конфиге"""
        invalid_json = '{"invalid": json}'
        
        with pytest.raises(json.JSONDecodeError):
            generate_link_from_json(
                tmp_link=vless_template,
                node_config_json=invalid_json,
                node_ip_or_domain="1.2.3.4",
                node_title="Node"
            )


class TestGenerateLinkEdgeCases:
    """Тесты граничных случаев"""
    
    def test_generate_link_simple_template(self, vless_config):
        """Генерация ссылки с минималистичным шаблоном"""
        simple_template = "vless://{user_uuid}@{{node___address}}:{{inbounds___0___port}}#{{node___title}}"
        
        success, result = generate_link_from_json(
            tmp_link=simple_template,
            node_config_json=vless_config,
            node_ip_or_domain="1.2.3.4",
            node_title="Node"
        )
        
        assert success is True
        assert "vless://{user_uuid}@1.2.3.4:443#Node" == result
        # Одинарный плейсхолдер остался
        assert "{user_uuid}" in result
        # Двойные исчезли
        assert "{{" not in result
    
    def test_generate_link_empty_title(self, vless_config, vless_template):
        """Пустое название ноды"""
        success, result = generate_link_from_json(
            tmp_link=vless_template,
            node_config_json=vless_config,
            node_ip_or_domain="1.2.3.4",
            node_title=""  # Пустое название
        )
        
        assert success is True
        assert result.endswith("#")  # Хештег присутствует, но после него пусто
    
    def test_generate_link_ipv6_address(self, vless_config, vless_template):
        """Использование IPv6 адреса"""
        success, result = generate_link_from_json(
            tmp_link=vless_template,
            node_config_json=vless_config,
            node_ip_or_domain="2001:db8::1",
            node_title="IPv6 Node"
        )
        
        assert success is True
        assert "@2001:db8::1:443" in result
    
    def test_generate_link_punycode_domain(self, vless_config, vless_template):
        """IDN домен (кириллица) должен конвертироваться в punycode"""
        success, result = generate_link_from_json(
            tmp_link=vless_template,
            node_config_json=vless_config,
            node_ip_or_domain="пример.рф",  # Кириллический домен
            node_title="RU Node"
        )
        
        assert success is True
        # Домен должен быть в punycode (IDNA)
        assert "@xn--e1afmkfd.xn--p1ai:443" in result
        # Не должно быть кириллицы в hostname части
        assert "пример.рф" not in result


class TestGenerateLinkSystemFields:
    """Тесты системных полей (node___address, node___title)"""
    
    def test_system_fields_override_config(self, vless_template):
        """Системные поля node___address и node___title переопределяют значения из конфига"""
        # Конфиг с полями, которые могут конфликтовать
        config_with_node_fields = {
            "node___address": "should_be_overridden",
            "node___title": "should_be_overridden",
            "inbounds": [
                {
                    "port": 443,
                    "protocol": "vless",
                    "streamSettings": {
                        "network": "raw",
                        "security": "reality",
                        "realitySettings": {
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
            node_ip_or_domain="real_address.com",  # Должно использоваться это
            node_title="Real Title"  # Должно использоваться это
        )
        
        assert success is True
        assert "@real_address.com:443" in result
        assert result.endswith("#Real%20Title")
        # Проверяем что значения из конфига НЕ использовались
        assert "should_be_overridden" not in result
