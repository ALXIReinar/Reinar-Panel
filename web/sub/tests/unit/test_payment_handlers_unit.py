"""
Unit тесты для вспомогательных функций Robokassa payment handlers.

Тестируем чистые функции без внешних зависимостей:
- payment_meta4signature_string() - сортировка и форматирование метаданных
- create_signature() - создание строки для подписи
- crypt_strategy - стратегии хеширования (MD5, SHA256)
"""
import pytest
import hashlib
from decimal import Decimal

from web.sub.api.robo_payment.handlers import (
    payment_meta4signature_string,
    create_signature,
    crypt_strategy,
    CryptStrategy
)


# Отключаем автоматическое использование db_seed для unit тестов
pytestmark = pytest.mark.usefixtures()


class TestPaymentMeta4SignatureString:
    """Unit тесты для payment_meta4signature_string()"""
    
    def test_sorts_keys_alphabetically(self):
        """
        Проверяем что ключи сортируются по алфавиту.
        
        Robokassa требует алфавитную сортировку Shp_ параметров.
        """
        # Arrange - специально в неправильном порядке
        payment_meta = {
            'Shp_user_id': 123,
            'Shp_csrf_token': 'token123',
            'Shp_sub_plan_id': 5,
            'Shp_expire_date': '2026-12-31',
        }
        
        # Act
        result = payment_meta4signature_string(payment_meta)
        
        # Assert - должны быть отсортированы: csrf < expire < sub_plan < user
        expected = "Shp_csrf_token=token123:Shp_expire_date=2026-12-31:Shp_sub_plan_id=5:Shp_user_id=123"
        assert result == expected
    
    
    def test_single_parameter(self):
        """Один параметр без сортировки"""
        # Arrange
        payment_meta = {'Shp_user_id': 999}
        
        # Act
        result = payment_meta4signature_string(payment_meta)
        
        # Assert
        assert result == "Shp_user_id=999"
    
    
    def test_empty_dict(self):
        """Пустой словарь возвращает пустую строку"""
        # Arrange
        payment_meta = {}
        
        # Act
        result = payment_meta4signature_string(payment_meta)
        
        # Assert
        assert result == ""
    
    
    def test_colon_separator(self):
        """Проверяем что параметры разделены двоеточием"""
        # Arrange
        payment_meta = {
            'Shp_a': 1,
            'Shp_b': 2,
            'Shp_c': 3,
        }
        
        # Act
        result = payment_meta4signature_string(payment_meta)
        
        # Assert
        assert result == "Shp_a=1:Shp_b=2:Shp_c=3"
        assert result.count(':') == 2
    
    
    def test_preserves_value_types(self):
        """Значения преобразуются в строки корректно"""
        # Arrange
        payment_meta = {
            'Shp_int': 123,
            'Shp_str': 'hello',
            'Shp_float': 99.99,
        }
        
        # Act
        result = payment_meta4signature_string(payment_meta)
        
        # Assert
        assert "Shp_int=123" in result
        assert "Shp_str=hello" in result
        assert "Shp_float=99.99" in result


class TestCreateSignature:
    """Unit тесты для create_signature()"""
    
    def test_signature_with_merchant_login(self):
        """
        Создание сигнатуры С merchant_login.
        
        Формат: {merchant_login}:{amount}:{order_id}:{password}:{payment_meta}
        """
        # Arrange
        robo_passw = "test_password_123"
        amount = 500
        order_id = 42
        payment_meta_str = "Shp_user_id=10"
        merchant_login = "test_merchant"
        
        # Act
        result = create_signature(
            robo_passw, amount, order_id, payment_meta_str, merchant_login
        )
        
        # Assert
        expected = "test_merchant:500:42:test_password_123:Shp_user_id=10"
        assert result == expected
    
    
    def test_signature_without_merchant_login(self):
        """
        Создание сигнатуры БЕЗ merchant_login (пустая строка).
        
        Формат: {amount}:{order_id}:{password}:{payment_meta}
        """
        # Arrange
        robo_passw = "secret_pass"
        amount = 1000
        order_id = 999
        payment_meta_str = "Shp_csrf_token=abc123"
        
        # Act
        result = create_signature(
            robo_passw, amount, order_id, payment_meta_str, merchant_login=''
        )
        
        # Assert
        expected = "1000:999:secret_pass:Shp_csrf_token=abc123"
        assert result == expected
        # Не должно быть двоеточия в начале
        assert not result.startswith(':')
    
    
    def test_signature_with_decimal_amount(self):
        """Сумма в формате Decimal корректно преобразуется"""
        # Arrange
        robo_passw = "pass"
        amount = Decimal("99.99")
        order_id = 1
        payment_meta_str = ""
        
        # Act
        result = create_signature(
            robo_passw, amount, order_id, payment_meta_str
        )
        
        # Assert
        assert "99.99" in result
    
    
    def test_signature_with_string_amount(self):
        """Сумма в формате строки работает корректно"""
        # Arrange
        robo_passw = "pass"
        amount = "250.50"
        order_id = 10
        payment_meta_str = "meta"
        
        # Act
        result = create_signature(
            robo_passw, amount, order_id, payment_meta_str
        )
        
        # Assert
        assert "250.50" in result
    
    
    def test_signature_format_structure(self):
        """Проверяем общую структуру сигнатуры"""
        # Arrange
        robo_passw = "pw"
        amount = 100
        order_id = 5
        payment_meta_str = "meta"
        merchant_login = "shop"
        
        # Act
        result = create_signature(
            robo_passw, amount, order_id, payment_meta_str, merchant_login
        )
        
        # Assert
        parts = result.split(':')
        assert len(parts) == 5  # merchant:amount:order:pass:meta
        assert parts[0] == "shop"
        assert parts[1] == "100"
        assert parts[2] == "5"
        assert parts[3] == "pw"
        assert parts[4] == "meta"


class TestCryptStrategy:
    """Unit тесты для стратегий хеширования"""
    
    def test_md5_hash(self):
        """MD5 хеширование работает корректно"""
        # Arrange
        test_string = "test_signature_string"
        test_bytes = test_string.encode('utf-8')
        
        # Act
        result = crypt_strategy['md5'](test_bytes)
        
        # Assert
        assert result is not None
        hex_digest = result.hexdigest()
        assert len(hex_digest) == 32  # MD5 всегда 32 символа
        # Проверяем что это валидный хекс
        assert all(c in '0123456789abcdef' for c in hex_digest)
    
    
    def test_sha256_hash(self):
        """SHA256 хеширование работает корректно"""
        # Arrange
        test_string = "another_test_signature"
        test_bytes = test_string.encode('utf-8')
        
        # Act
        result = crypt_strategy['sha256'](test_bytes)
        
        # Assert
        assert result is not None
        hex_digest = result.hexdigest()
        assert len(hex_digest) == 64  # SHA256 всегда 64 символа
        assert all(c in '0123456789abcdef' for c in hex_digest)
    
    
    def test_md5_deterministic(self):
        """MD5 хеш одинаковый для одинаковых входов"""
        # Arrange
        test_bytes = "same_input".encode('utf-8')
        
        # Act
        hash1 = crypt_strategy['md5'](test_bytes).hexdigest()
        hash2 = crypt_strategy['md5'](test_bytes).hexdigest()
        
        # Assert
        assert hash1 == hash2
    
    
    def test_sha256_deterministic(self):
        """SHA256 хеш одинаковый для одинаковых входов"""
        # Arrange
        test_bytes = "consistent_input".encode('utf-8')
        
        # Act
        hash1 = crypt_strategy['sha256'](test_bytes).hexdigest()
        hash2 = crypt_strategy['sha256'](test_bytes).hexdigest()
        
        # Assert
        assert hash1 == hash2
    
    
    def test_md5_different_inputs_different_hashes(self):
        """Разные входы дают разные MD5 хеши"""
        # Arrange
        bytes1 = "input1".encode('utf-8')
        bytes2 = "input2".encode('utf-8')
        
        # Act
        hash1 = crypt_strategy['md5'](bytes1).hexdigest()
        hash2 = crypt_strategy['md5'](bytes2).hexdigest()
        
        # Assert
        assert hash1 != hash2
    
    
    def test_crypt_strategy_class_md5(self):
        """Проверяем CryptStrategy.md5 напрямую"""
        # Arrange
        test_bytes = "direct_test".encode('utf-8')
        
        # Act
        result = CryptStrategy.md5(test_bytes)
        
        # Assert
        assert isinstance(result, type(hashlib.md5()))
        assert len(result.hexdigest()) == 32
    
    
    def test_crypt_strategy_class_sha256(self):
        """Проверяем CryptStrategy.sha256 напрямую"""
        # Arrange
        test_bytes = "direct_sha_test".encode('utf-8')
        
        # Act
        result = CryptStrategy.sha256(test_bytes)
        
        # Assert
        assert isinstance(result, type(hashlib.sha256()))
        assert len(result.hexdigest()) == 64


class TestIntegrationHandlers:
    """Integration тесты между функциями handlers"""
    
    def test_full_signature_pipeline_md5(self):
        """
        Полный пайплайн: payment_meta → signature_string → MD5 hash.
        
        Имитируем реальный flow создания подписи для Robokassa.
        """
        # Arrange
        payment_meta = {
            'Shp_user_id': 123,
            'Shp_sub_plan_id': 5,
            'Shp_csrf_token': 'abc123xyz',
        }
        robo_passw = "test_password"
        amount = 500
        order_id = 42
        merchant_login = "test_shop"
        
        # Act
        # Шаг 1: форматируем метаданные
        meta_str = payment_meta4signature_string(payment_meta)
        
        # Шаг 2: создаём строку сигнатуры
        signature_str = create_signature(
            robo_passw, amount, order_id, meta_str, merchant_login
        )
        
        # Шаг 3: хешируем MD5
        signature_hash = crypt_strategy['md5'](signature_str.encode('utf-8')).hexdigest()
        
        # Assert
        assert len(signature_hash) == 32
        # Проверяем что meta_str правильно отсортирован
        assert meta_str.startswith('Shp_csrf_token=')
        # Проверяем формат signature_str
        assert merchant_login in signature_str
        assert str(amount) in signature_str
        assert str(order_id) in signature_str
    
    
    def test_full_signature_pipeline_sha256(self):
        """Полный пайплайн с SHA256 (используется в production)"""
        # Arrange
        payment_meta = {
            'Shp_expire_date': '2026-12-31',
            'Shp_user_id': 999,
        }
        robo_passw = "production_secret"
        amount = Decimal("1999.99")
        order_id = 100500
        
        # Act
        meta_str = payment_meta4signature_string(payment_meta)
        signature_str = create_signature(
            robo_passw, amount, order_id, meta_str, merchant_login=''
        )
        signature_hash = crypt_strategy['sha256'](signature_str.encode('utf-8')).hexdigest()
        
        # Assert
        assert len(signature_hash) == 64
        # Проверяем что можем повторить хеш (детерминизм)
        signature_hash_2 = crypt_strategy['sha256'](signature_str.encode('utf-8')).hexdigest()
        assert signature_hash == signature_hash_2
