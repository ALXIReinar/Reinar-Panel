"""
Юнит-тесты для валидации схем авторизации (admins_schema.py).
Проверяет ограничения для паролей, user_agent, IP и логинов.
"""
import pytest
from pydantic import ValidationError

from web.schemas.admins_schema import (
    ValidatePasswSchema,
    TokenPayloadSchema,
    UpdatePasswSchema,
    AdminLogInSchema,
    AdminRegSchema
)


class TestValidatePasswSchema:
    """Тесты валидации паролей"""

    def test_valid_password(self):
        """Валидный пароль со всеми требованиями"""
        schema = ValidatePasswSchema(passw="TestPass123!")
        assert schema.passw == "TestPass123!"

    def test_valid_password_minimal(self):
        """Минимальный валидный пароль (8 символов)"""
        schema = ValidatePasswSchema(passw="Aa1!bcde")
        assert schema.passw == "Aa1!bcde"

    def test_valid_password_with_various_special_chars(self):
        """Пароль с различными спецсимволами"""
        valid_passwords = [
            "TestPass1!",
            "TestPass1@",
            "TestPass1#",
            "TestPass1$",
            "TestPass1%",
            "TestPass1^",
            "TestPass1&",
            "TestPass1*",
            "TestPass1(",
            "TestPass1)",
            "TestPass1-",
            "TestPass1_",
            "TestPass1+",
            "TestPass1=",
        ]
        for passw in valid_passwords:
            schema = ValidatePasswSchema(passw=passw)
            assert schema.passw == passw

    def test_password_too_short(self):
        """Пароль короче 8 символов"""
        with pytest.raises(ValidationError) as exc_info:
            ValidatePasswSchema(passw="Test1!")
        
        assert "String shorter 8 characters" in str(exc_info.value)

    def test_password_too_long(self):
        """Пароль длиннее 72 байт"""
        # Создаём пароль длиной 73 байта
        long_password = "A1!" + "a" * 70  # 73 символа = 73 байта
        with pytest.raises(ValidationError) as exc_info:
            ValidatePasswSchema(passw=long_password)
        
        assert "Password too long (max 72 bytes)" in str(exc_info.value)

    def test_password_exactly_72_bytes(self):
        """Пароль ровно 72 байта (граничный случай)"""
        # 72 символа ASCII = 72 байта
        password_72 = "A1!" + "a" * 69  # Ровно 72 символа
        schema = ValidatePasswSchema(passw=password_72)
        assert len(schema.passw.encode('utf-8')) == 72

    def test_password_with_cyrillic(self):
        """Пароль с русскими буквами"""
        with pytest.raises(ValidationError) as exc_info:
            ValidatePasswSchema(passw="TestПароль1!")
        
        assert "Password must consist of English chars only" in str(exc_info.value)

    def test_password_with_spaces(self):
        """Пароль с пробелами"""
        with pytest.raises(ValidationError) as exc_info:
            ValidatePasswSchema(passw="Test Pass123!")
        
        assert "Password must not contain spaces" in str(exc_info.value)

    def test_password_without_digit(self):
        """Пароль без цифр"""
        with pytest.raises(ValidationError) as exc_info:
            ValidatePasswSchema(passw="TestPass!")
        
        assert "Password does not match the conditions" in str(exc_info.value)

    def test_password_without_special_char(self):
        """Пароль без спецсимволов"""
        with pytest.raises(ValidationError) as exc_info:
            ValidatePasswSchema(passw="TestPass123")
        
        assert "Password does not match the conditions" in str(exc_info.value)

    def test_password_without_uppercase(self):
        """Пароль без заглавных букв"""
        with pytest.raises(ValidationError) as exc_info:
            ValidatePasswSchema(passw="testpass123!")
        
        assert "Password does not match the conditions" in str(exc_info.value)

    def test_password_only_uppercase_no_digit(self):
        """Пароль только заглавные буквы и спецсимвол, но без цифр"""
        with pytest.raises(ValidationError) as exc_info:
            ValidatePasswSchema(passw="TESTPASS!")
        
        assert "Password does not match the conditions" in str(exc_info.value)

    def test_password_strip_whitespace(self):
        """Пароль с пробелами в начале и конце (должны обрезаться)"""
        schema = ValidatePasswSchema(passw="  TestPass123!  ")
        assert schema.passw == "TestPass123!"


class TestTokenPayloadSchema:
    """Тесты валидации токенов (user_agent и IP)"""

    def test_valid_token_payload(self):
        """Валидные данные токена"""
        schema = TokenPayloadSchema(
            id=1,
            user_agent="Mozilla/5.0",
            ip="192.168.1.1"
        )
        assert schema.id == 1
        assert schema.user_agent == "Mozilla/5.0"
        assert schema.ip == "192.168.1.1"

    def test_valid_ipv6_address(self):
        """Валидный IPv6 адрес (до 45 символов)"""
        ipv6 = "2001:0db8:85a3:0000:0000:8a2e:0370:7334"  # 39 символов
        schema = TokenPayloadSchema(
            id=1,
            user_agent="Mozilla/5.0",
            ip=ipv6
        )
        assert schema.ip == ipv6

    def test_user_agent_max_length(self):
        """User agent ровно 200 символов (граничный случай)"""
        ua = "A" * 200
        schema = TokenPayloadSchema(
            id=1,
            user_agent=ua,
            ip="127.0.0.1"
        )
        assert len(schema.user_agent) == 200

    def test_user_agent_too_long_validation_error(self):
        """User agent длиннее 200 символов вызывает ошибку валидации"""
        ua = "A" * 250
        with pytest.raises(ValidationError):
            TokenPayloadSchema(
                id=1,
                user_agent=ua,
                ip="127.0.0.1"
            )

    def test_user_agent_html_escaping(self):
        """HTML символы в user_agent должны экранироваться"""
        ua = "<script>alert('xss')</script>"
        schema = TokenPayloadSchema(
            id=1,
            user_agent=ua,
            ip="127.0.0.1"
        )
        # HTML должен быть экранирован
        assert "<script>" not in schema.user_agent
        assert "&lt;script&gt;" in schema.user_agent

    def test_user_agent_control_characters_removed(self):
        """Управляющие символы должны удаляться из user_agent"""
        ua = "Mozilla\x00\x01\x1f/5.0"
        schema = TokenPayloadSchema(
            id=1,
            user_agent=ua,
            ip="127.0.0.1"
        )
        # Управляющие символы (< 32) должны быть удалены
        assert "\x00" not in schema.user_agent
        assert "\x01" not in schema.user_agent
        assert "\x1f" not in schema.user_agent
        assert "Mozilla" in schema.user_agent

    def test_ip_too_long_validation_error(self):
        """IP длиннее 45 символов должен вызывать ошибку"""
        long_ip = "1" * 46
        with pytest.raises(ValidationError):
            TokenPayloadSchema(
                id=1,
                user_agent="Mozilla/5.0",
                ip=long_ip
            )

    def test_ip_exactly_45_chars(self):
        """IP ровно 45 символов (граничный случай для длинного IPv6)"""
        # Самый длинный IPv6 с зонами может быть до 45 символов
        # Создаём строку ровно 45 символов
        ip_45 = "2001:0db8:85a3:0000:0000:8a2e:0370:7334%eth00"  # Ровно 45 символов
        schema = TokenPayloadSchema(
            id=1,
            user_agent="Mozilla/5.0",
            ip=ip_45
        )
        assert len(schema.ip) == 45


class TestUpdatePasswSchema:
    """Тесты схемы обновления пароля"""

    def test_valid_update_passw_schema(self):
        """Валидные данные для обновления пароля"""
        schema = UpdatePasswSchema(
            admin_id=1,
            passw="NewPass123!"
        )
        assert schema.admin_id == 1
        assert schema.passw == "NewPass123!"

    def test_update_passw_inherits_validation(self):
        """UpdatePasswSchema наследует валидацию пароля"""
        with pytest.raises(ValidationError) as exc_info:
            UpdatePasswSchema(
                admin_id=1,
                passw="weak"
            )
        assert "String shorter 8 characters" in str(exc_info.value)


class TestAdminLogInSchema:
    """Тесты схемы входа админа"""

    def test_valid_login_schema(self):
        """Валидные данные для входа"""
        schema = AdminLogInSchema(
            login="admin123",
            passw="TestPass123!"
        )
        assert schema.login == "admin123"
        assert schema.passw == "TestPass123!"

    def test_login_min_length(self):
        """Логин минимальной длины (3 символа)"""
        schema = AdminLogInSchema(
            login="abc",
            passw="TestPass123!"
        )
        assert schema.login == "abc"

    def test_login_too_short(self):
        """Логин короче 3 символов"""
        with pytest.raises(ValidationError):
            AdminLogInSchema(
                login="ab",
                passw="TestPass123!"
            )

    def test_login_max_length(self):
        """Логин максимальной длины (128 символов)"""
        long_login = "a" * 128
        schema = AdminLogInSchema(
            login=long_login,
            passw="TestPass123!"
        )
        assert len(schema.login) == 128

    def test_login_too_long(self):
        """Логин длиннее 128 символов"""
        too_long_login = "a" * 129
        with pytest.raises(ValidationError):
            AdminLogInSchema(
                login=too_long_login,
                passw="TestPass123!"
            )


class TestAdminRegSchema:
    """Тесты схемы регистрации админа"""

    def test_valid_registration_schema(self):
        """Валидные данные для регистрации"""
        schema = AdminRegSchema(
            login="newadmin",
            passw="TestPass123!"
        )
        assert schema.login == "newadmin"
        assert schema.passw == "TestPass123!"

    def test_registration_login_validation(self):
        """Валидация логина при регистрации"""
        with pytest.raises(ValidationError):
            AdminRegSchema(
                login="ab",  # Слишком короткий
                passw="TestPass123!"
            )

    def test_registration_password_validation(self):
        """Валидация пароля при регистрации (наследуется от ValidatePasswSchema)"""
        with pytest.raises(ValidationError) as exc_info:
            AdminRegSchema(
                login="newadmin",
                passw="weak"
            )
        assert "String shorter 8 characters" in str(exc_info.value)

    def test_registration_both_fields_validated(self):
        """Валидация обоих полей одновременно"""
        schema = AdminRegSchema(
            login="validuser",
            passw="ValidPass123!"
        )
        assert schema.login == "validuser"
        assert schema.passw == "ValidPass123!"
