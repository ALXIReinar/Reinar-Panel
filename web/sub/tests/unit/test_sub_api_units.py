"""
Unit-тесты для чистых функций sub_api.py (без внешних зависимостей).

Тестируем только функции преобразования данных:
- error_messages_for_client: генерация fake vless-ссылок
- process2vpn_client_format: преобразование в base64

Тесты для executing_link_processing находятся в integration-тестах,
так как эта функция работает с реальными скриптами из БД.
"""
import pytest
import base64
import urllib.parse

from web.sub.api.sub_api import (
    error_messages_for_client,
    process2vpn_client_format,
)


class TestErrorMessagesForClient:
    """Unit-тесты для error_messages_for_client"""
    
    def test_single_message(self):
        """Генерация одного сообщения об ошибке"""
        # Arrange
        message = "Вы израсходовали лимит трафика"
        
        # Act
        result = error_messages_for_client(message)
        
        # Assert
        assert len(result) == 1
        assert result[0].startswith('vless://00000000-0000-0000-0000-000000000000@127.0.0.1:443')
        assert urllib.parse.quote(message) in result[0]
    
    def test_multiple_messages(self):
        """Генерация нескольких сообщений"""
        # Arrange
        msg1 = "Ошибка 1"
        msg2 = "Ошибка 2"
        msg3 = "Ошибка 3"
        
        # Act
        result = error_messages_for_client(msg1, msg2, msg3)
        
        # Assert
        assert len(result) == 3
        assert urllib.parse.quote(msg1) in result[0]
        assert urllib.parse.quote(msg2) in result[1]
        assert urllib.parse.quote(msg3) in result[2]
    
    def test_special_characters_encoding(self):
        """URL-кодирование специальных символов"""
        # Arrange
        message = "Тестовое сообщение с пробелами и спецсимволами: #, &, ?"
        
        # Act
        result = error_messages_for_client(message)
        
        # Assert
        # Проверяем что спецсимволы закодированы
        encoded_message = urllib.parse.quote(message)
        assert encoded_message in result[0]
        assert ' ' not in result[0].split('#')[1]  # Пробелы должны быть закодированы


class TestProcess2VpnClientFormat:
    """Unit-тесты для process2vpn_client_format"""
    
    def test_list_to_base64(self):
        """Преобразование списка ссылок в base64"""
        # Arrange
        links = [
            "vless://uuid1@server1:443",
            "vmess://base64data",
            "trojan://password@server2:443"
        ]
        
        # Act
        result = process2vpn_client_format(links)
        
        # Assert
        # Декодируем обратно
        decoded = base64.b64decode(result).decode()
        assert "vless://uuid1@server1:443" in decoded
        assert "vmess://base64data" in decoded
        assert "trojan://password@server2:443" in decoded
        # Проверяем что разделены переносами строк
        assert decoded.count('\n') == 2  # 3 ссылки = 2 переноса
    
    def test_string_to_base64(self):
        """Преобразование строки в base64"""
        # Arrange
        single_link = "vless://uuid@server:443"
        
        # Act
        result = process2vpn_client_format(single_link)
        
        # Assert
        decoded = base64.b64decode(result).decode()
        assert decoded == single_link
    
    def test_with_description(self):
        """Преобразование с добавлением описания"""
        # Arrange
        links = ["vless://uuid@server:443"]
        description = "Test subscription"
        
        # Act
        result = process2vpn_client_format(links, description=description)
        
        # Assert
        decoded = base64.b64decode(result).decode()
        # Описание должно быть в формате #note:encoded_description
        assert decoded.startswith(f"#note:{urllib.parse.quote(description)}\n")
        assert "vless://uuid@server:443" in decoded
    
    def test_empty_list(self):
        """Преобразование пустого списка"""
        # Arrange
        links = []
        
        # Act
        result = process2vpn_client_format(links)
        
        # Assert
        decoded = base64.b64decode(result).decode()
        assert decoded == ""
    
    def test_cyrillic_in_description(self):
        """Преобразование описания с кириллицей"""
        # Arrange
        links = ["vless://uuid@server:443"]
        description = "Тестовая подписка"
        
        # Act
        result = process2vpn_client_format(links, description=description)
        
        # Assert
        decoded = base64.b64decode(result).decode()
        # Кириллица должна быть URL-закодирована
        assert "#note:" in decoded
        assert "vless://uuid@server:443" in decoded

