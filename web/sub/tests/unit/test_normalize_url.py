"""
Unit тесты для функции normalize_url()

Проверяет корректное URL кодирование query параметров:
- Кириллица и non-ASCII символы
- Base64 спецсимволы (+, /, =)
- Пробелы
- Защита от двойного кодирования
- Сохранение scheme, userinfo, hostname, port, fragment

Запуск:
    pytest web/sub/tests/unit/test_normalize_url.py -v
"""
import pytest
from web.sub.api.handlers.prepare_func import normalize_url


class TestNormalizeUrl:
    """Тесты для normalize_url() функции"""
    
    def test_base64_symbols_encoded(self):
        """
        Base64 спецсимволы должны быть закодированы prepare_sub скриптом
        
        ВАЖНО: parse_qsl() декодирует '+' в пробел, затем urlencode() кодирует в '%20'.
        Это нормальное поведение для application/x-www-form-urlencoded.
        
        В реальности prepare_sub скрипты уже кодируют base64 через quote(key, safe=""),
        поэтому normalize_url() получает УЖЕ закодированный %2B (не сырой +).
        """
        # Реальный кейс: prepare_sub уже закодировал base64
        url = "vless://uuid@example.com:443?pbk=ABC%2BDEF%2FGHI%3D&fp=chrome#node"
        result = normalize_url(url)
        
        # Уже закодированные символы остаются закодированными
        assert "ABC%2BDEF%2FGHI%3D" in result
        # Нет двойного кодирования
        assert "%252B" not in result
        assert "%252F" not in result
        assert "%253D" not in result
    
    def test_cyrillic_domain_in_query(self):
        """Кириллические домены в query параметрах должны быть закодированы"""
        url = "vless://uuid@example.com:443?sni=пример.рф&fp=chrome#node"
        result = normalize_url(url)
        
        # Кириллица закодирована
        assert "%D0%BF%D1%80%D0%B8%D0%BC%D0%B5%D1%80.%D1%80%D1%84" in result
        assert "пример" not in result
        assert "рф" not in result
    
    def test_spaces_encoded(self):
        """Пробелы в query параметрах должны быть закодированы"""
        url = "vless://uuid@example.com:443?path=/api test&fp=chrome#node"
        result = normalize_url(url)
        
        # Пробелы закодированы
        assert "%20" in result or "+" in result  # urllib может использовать любой вариант
        assert " " not in result.split("?")[1].split("#")[0]
    
    def test_no_double_encoding(self):
        """Уже закодированные символы не должны кодироваться повторно"""
        url = "vless://uuid@example.com:443?pbk=ABC%2BDEF%2FGHI%3D&fp=chrome#node"
        result = normalize_url(url)
        
        # Должно остаться %2B, а не превратиться в %252B
        assert "ABC%2BDEF%2FGHI%3D" in result
        assert "%252B" not in result  # Нет двойного кодирования
        assert "%252F" not in result
        assert "%253D" not in result
    
    def test_safe_characters_not_encoded(self):
        """Безопасные символы (A-Z, a-z, 0-9, -, _, ., ~) не должны кодироваться"""
        url = "vless://uuid@example.com:443?fp=chrome&type=tcp&security=tls#My-Node_1.2"
        result = normalize_url(url)
        
        # Безопасные символы остались без изменений
        assert "fp=chrome" in result
        assert "type=tcp" in result
        assert "security=tls" in result
        # Fragment тоже не должен пострадать (обрабатывается отдельно)
        assert "#My-Node_1.2" in result
    
    def test_preserves_scheme(self):
        """Scheme (vless://, vmess://, и т.д.) не должен изменяться"""
        schemes = [
            "vless://uuid@example.com:443?fp=chrome#node",
            "vmess://uuid@example.com:443?fp=chrome#node",
            "trojan://password@example.com:443?fp=chrome#node",
            "ss://method:password@example.com:443?fp=chrome#node",
            "hysteria2://password@example.com:443?fp=chrome#node",
            "wireguard://private_key@example.com:51820?fp=chrome#node",
        ]
        
        for url in schemes:
            result = normalize_url(url)
            scheme = url.split("://")[0]
            assert result.startswith(f"{scheme}://")
    
    def test_preserves_userinfo(self):
        """Userinfo часть (между :// и @) не должна изменяться"""
        # WireGuard с закодированным приватным ключом в userinfo
        url = "wireguard://ABC%2BDEF%2FGHI%3D@example.com:51820?public_key=XYZ#node"
        result = normalize_url(url)
        
        # Userinfo остался без изменений
        assert "wireguard://ABC%2BDEF%2FGHI%3D@example.com" in result
        # НЕТ двойного кодирования userinfo
        assert "%252B" not in result
    
    def test_preserves_hostname_and_port(self):
        """Hostname и port не должны изменяться"""
        url = "vless://uuid@192.168.1.100:8443?fp=chrome#node"
        result = normalize_url(url)
        
        # Hostname и port остались без изменений
        assert "@192.168.1.100:8443?" in result
    
    def test_preserves_fragment(self):
        """Fragment (#node_title) не должен изменяться"""
        # Fragment уже закодирован в generate_link_from_json
        url = "vless://uuid@example.com:443?fp=chrome#My%20Node%20Title"
        result = normalize_url(url)
        
        # Fragment остался без изменений
        assert "#My%20Node%20Title" in result
        # НЕТ двойного кодирования fragment
        assert "%2520" not in result
    
    def test_empty_query(self):
        """URL без query параметров должен остаться без изменений"""
        url = "vless://uuid@example.com:443#node"
        result = normalize_url(url)
        
        assert result == url
    
    def test_multiple_query_params(self):
        """Несколько query параметров должны обрабатываться корректно"""
        url = "vless://uuid@example.com:443?encryption=none&flow=xtls+vision&security=reality&sni=ads.x5.ru&fp=chrome&pbk=ABC/DEF=&sid=709c400f#node"
        result = normalize_url(url)
        
        # Все параметры присутствуют
        assert "encryption=none" in result
        assert "flow=xtls" in result
        assert "security=reality" in result
        assert "sni=ads.x5.ru" in result
        assert "fp=chrome" in result
        
        # Спецсимволы закодированы
        assert "%2F" in result  # / в pbk
        assert "%3D" in result  # = в pbk
        
        # Fragment сохранён
        assert "#node" in result
    
    def test_ipv6_hostname(self):
        """IPv6 адрес в hostname не должен ломаться"""
        url = "vless://uuid@[2001:db8::1]:443?fp=chrome#node"
        result = normalize_url(url)
        
        # IPv6 адрес остался без изменений
        assert "@[2001:db8::1]:443?" in result
    
    def test_special_characters_in_query_values(self):
        """Специальные символы в query значениях должны кодироваться"""
        url = "vless://uuid@example.com:443?path=/api?test=1&mode=test&fp=chrome#node"
        result = normalize_url(url)
        
        # Вопросительный знак в path должен быть закодирован
        assert "%3F" in result
    
    def test_emoji_in_query(self):
        """Эмодзи в query параметрах должны кодироваться"""
        url = "vless://uuid@example.com:443?comment=test🚀&fp=chrome#node"
        result = normalize_url(url)
        
        # Эмодзи закодированы
        assert "🚀" not in result
        assert "comment=" in result
        # Эмодзи превратится в набор %XX последовательностей
        assert "comment=test%F0%9F%9A%80" in result
    
    def test_blank_value_preserved(self):
        """Пустые значения query параметров должны сохраняться"""
        url = "vless://uuid@example.com:443?encryption=&fp=chrome#node"
        result = normalize_url(url)
        
        # Пустое значение сохранено
        assert "encryption=" in result
        assert "fp=chrome" in result
    
    def test_ampersand_separated_params(self):
        """Параметры разделённые & должны остаться разделёнными &"""
        url = "vless://uuid@example.com:443?a=1&b=2&c=3#node"
        result = normalize_url(url)
        
        # Параметры разделены &
        assert "a=1&b=2&c=3" in result
    
    def test_punycode_domain_in_query_not_affected(self):
        """Punycode домены в query параметрах не должны ломаться"""
        # Если админ уже сохранил домен в Punycode
        url = "vless://uuid@example.com:443?sni=xn--e1afmkfd.xn--p1ai&fp=chrome#node"
        result = normalize_url(url)
        
        # Punycode остался без изменений (это валидный ASCII)
        assert "sni=xn--e1afmkfd.xn--p1ai" in result
    
    def test_real_wireguard_link(self):
        """Реальный WireGuard link с закодированными ключами"""
        url = "wireguard://ABC%2BDEF%2FGHI%3D@192.168.1.100:51820?public_key=XYZ%2B123%2F456%3D&local_address=10.0.0.2%2F32&reserved=10%2C20%2C30#My%20Node"
        result = normalize_url(url)
        
        # Userinfo остался без двойного кодирования
        assert "wireguard://ABC%2BDEF%2FGHI%3D@192.168.1.100:51820?" in result
        
        # Query параметры не пострадали от двойного кодирования
        assert "public_key=XYZ%2B123%2F456%3D" in result
        assert "local_address=10.0.0.2%2F32" in result
        assert "reserved=10%2C20%2C30" in result
        
        # НЕТ двойного кодирования
        assert "%252B" not in result
        assert "%252F" not in result
        assert "%253D" not in result
        assert "%252C" not in result
        
        # Fragment сохранён
        assert "#My%20Node" in result
    
    def test_real_vless_reality_link(self):
        """Реальный VLESS Reality link"""
        url = "vless://550e8400-e29b-41d4-a716-446655440000@example.com:443?encryption=none&flow=xtls-rprx-vision&security=reality&sni=ads.x5.ru&fp=chrome&pbk=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop&sid=709c400f8da05efa&type=tcp#MyNode"
        result = normalize_url(url)
        
        # Все параметры присутствуют и корректны
        assert "encryption=none" in result
        assert "flow=xtls-rprx-vision" in result
        assert "security=reality" in result
        assert "sni=ads.x5.ru" in result
        assert "fp=chrome" in result
        assert "pbk=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop" in result
        assert "sid=709c400f8da05efa" in result
        assert "type=tcp" in result
        assert "#MyNode" in result


@pytest.mark.parametrize("input_url,expected_contains", [
    # Кириллица
    ("vless://uuid@example.com?sni=тест.рф#node", ["%D1%82%D0%B5%D1%81%D1%82.%D1%80%D1%84"]),
    # Base64 (УЖЕ закодированный prepare_sub скриптом)
    ("vless://uuid@example.com?pbk=ABC%2BDEF%2FGHI%3D#node", ["ABC%2BDEF%2FGHI%3D"]),
    # Пробелы
    ("vless://uuid@example.com?path=/api test#node", ["api%20test"]),
    # Безопасные символы
    ("vless://uuid@example.com?fp=chrome&type=tcp#node", ["fp=chrome", "type=tcp"]),
])
def test_normalize_url_parametrized(input_url, expected_contains):
    """Параметризованные тесты для различных случаев"""
    result = normalize_url(input_url)
    
    for expected in expected_contains:
        assert expected in result, f"Expected '{expected}' in result, but got: {result}"
