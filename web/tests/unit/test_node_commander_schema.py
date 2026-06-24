"""
Unit тесты для валидации схемы ExecCMDNodeSchema
Тестируют безопасность команд и защиту от command injection
"""
import pytest
from pydantic import ValidationError

from web.schemas.node_commander_schema import ExecCMDNodeSchema


class TestDangerousCommandBlocking:
    """Тесты блокировки опасных паттернов команд"""
    
    def test_block_subshell_execution(self):
        """Блокировка subshell execution с круглыми скобками"""
        with pytest.raises(ValidationError) as exc_info:
            ExecCMDNodeSchema(
                node_proto_id=1,
                private_ip="192.168.1.1",
                api_port=8080,
                cmd="(whoami)"
            )
        assert "опасный паттерн" in str(exc_info.value).lower()
    
    def test_block_pipe_operator(self):
        """Блокировка pipe operator |"""
        with pytest.raises(ValidationError) as exc_info:
            ExecCMDNodeSchema(
                node_proto_id=1,
                private_ip="192.168.1.1",
                api_port=8080,
                cmd="ls | grep test"
            )
        assert "опасный паттерн" in str(exc_info.value).lower()
    
    def test_block_hex_encoding(self):
        """Блокировка hex encoding для обхода фильтров"""
        with pytest.raises(ValidationError) as exc_info:
            ExecCMDNodeSchema(
                node_proto_id=1,
                private_ip="192.168.1.1",
                api_port=8080,
                cmd="echo \\x3b"
            )
        assert "опасный паттерн" in str(exc_info.value).lower()
    
    def test_block_brace_expansion(self):
        """Блокировка brace expansion {1,2,3}"""
        with pytest.raises(ValidationError) as exc_info:
            ExecCMDNodeSchema(
                node_proto_id=1,
                private_ip="192.168.1.1",
                api_port=8080,
                cmd="echo {1,2,3}"
            )
        assert "опасный паттерн" in str(exc_info.value).lower()
    
    def test_block_ifs_injection(self):
        """Блокировка IFS injection"""
        with pytest.raises(ValidationError) as exc_info:
            ExecCMDNodeSchema(
                node_proto_id=1,
                private_ip="192.168.1.1",
                api_port=8080,
                cmd="cat$IFS/etc/passwd"
            )
        assert "опасный паттерн" in str(exc_info.value).lower()
    
    def test_block_semicolon_separator(self):
        """Блокировка command separator точка с запятой"""
        with pytest.raises(ValidationError) as exc_info:
            ExecCMDNodeSchema(
                node_proto_id=1,
                private_ip="192.168.1.1",
                api_port=8080,
                cmd="ls; whoami"
            )
        assert "опасный паттерн" in str(exc_info.value).lower()
    
    def test_block_ampersand_separator(self):
        """Блокировка command separator &&"""
        with pytest.raises(ValidationError) as exc_info:
            ExecCMDNodeSchema(
                node_proto_id=1,
                private_ip="192.168.1.1",
                api_port=8080,
                cmd="ls && whoami"
            )
        assert "опасный паттерн" in str(exc_info.value).lower()
    
    def test_block_dollar_sign_variable(self):
        """Блокировка dollar sign для переменных"""
        with pytest.raises(ValidationError) as exc_info:
            ExecCMDNodeSchema(
                node_proto_id=1,
                private_ip="192.168.1.1",
                api_port=8080,
                cmd="echo $USER"
            )
        assert "опасный паттерн" in str(exc_info.value).lower()
    
    def test_block_redirect_to_dev(self):
        """Блокировка redirect в /dev/"""
        with pytest.raises(ValidationError) as exc_info:
            ExecCMDNodeSchema(
                node_proto_id=1,
                private_ip="192.168.1.1",
                api_port=8080,
                cmd="ls > /dev/null"
            )
        assert "опасный паттерн" in str(exc_info.value).lower()
    
    def test_block_write_to_etc(self):
        """Блокировка записи в /etc/"""
        with pytest.raises(ValidationError) as exc_info:
            ExecCMDNodeSchema(
                node_proto_id=1,
                private_ip="192.168.1.1",
                api_port=8080,
                cmd="echo test > /etc/test"
            )
        assert "опасный паттерн" in str(exc_info.value).lower()
    
    def test_block_recursive_delete_root(self):
        """Блокировка рекурсивного удаления от корня"""
        with pytest.raises(ValidationError) as exc_info:
            ExecCMDNodeSchema(
                node_proto_id=1,
                private_ip="192.168.1.1",
                api_port=8080,
                cmd="rm -rf /*"
            )
        assert "опасный паттерн" in str(exc_info.value).lower()
    
    def test_block_backtick_substitution(self):
        """Блокировка command substitution с backticks"""
        with pytest.raises(ValidationError) as exc_info:
            ExecCMDNodeSchema(
                node_proto_id=1,
                private_ip="192.168.1.1",
                api_port=8080,
                cmd="echo `whoami`"
            )
        assert "опасный паттерн" in str(exc_info.value).lower()
    
    def test_block_command_substitution_dollar(self):
        """Блокировка command substitution $(...)"""
        with pytest.raises(ValidationError) as exc_info:
            ExecCMDNodeSchema(
                node_proto_id=1,
                private_ip="192.168.1.1",
                api_port=8080,
                cmd="echo $(whoami)"
            )
        assert "опасный паттерн" in str(exc_info.value).lower()
    
    def test_block_newline_injection(self):
        """Блокировка newline injection"""
        with pytest.raises(ValidationError) as exc_info:
            ExecCMDNodeSchema(
                node_proto_id=1,
                private_ip="192.168.1.1",
                api_port=8080,
                cmd="ls\nwhoami"
            )
        assert "опасный паттерн" in str(exc_info.value).lower()


class TestPydanticValidation:
    """Тесты базовой валидации Pydantic (длина, типы)"""
    
    def test_command_too_short(self):
        """Команда слишком короткая (min_length=2)"""
        with pytest.raises(ValidationError) as exc_info:
            ExecCMDNodeSchema(
                node_proto_id=1,
                private_ip="192.168.1.1",
                api_port=8080,
                cmd="l"
            )
        # Pydantic validation error для min_length
        assert "at least 2 characters" in str(exc_info.value).lower() or "min_length" in str(exc_info.value).lower()
    
    def test_command_too_long(self):
        """Команда слишком длинная (max_length=100)"""
        long_cmd = "a" * 101
        with pytest.raises(ValidationError) as exc_info:
            ExecCMDNodeSchema(
                node_proto_id=1,
                private_ip="192.168.1.1",
                api_port=8080,
                cmd=long_cmd
            )
        assert "at most 100 characters" in str(exc_info.value).lower() or "max_length" in str(exc_info.value).lower()
    
    def test_invalid_port_negative(self):
        """Негативный порт (gt=0)"""
        with pytest.raises(ValidationError):
            ExecCMDNodeSchema(
                node_proto_id=1,
                private_ip="192.168.1.1",
                api_port=-1,
                cmd="ls -la"
            )
    
    def test_invalid_port_too_large(self):
        """Порт больше 65535 (le=65535)"""
        with pytest.raises(ValidationError):
            ExecCMDNodeSchema(
                node_proto_id=1,
                private_ip="192.168.1.1",
                api_port=70000,
                cmd="ls -la"
            )
    
    def test_invalid_ip_address(self):
        """Невалидный IP адрес"""
        with pytest.raises(ValidationError):
            ExecCMDNodeSchema(
                node_proto_id=1,
                private_ip="999.999.999.999",
                api_port=8080,
                cmd="ls -la"
            )


class TestAllowedCommands:
    """Тесты разрешённых безопасных команд"""
    
    def test_allow_ls_command(self):
        """Разрешена команда ls -la"""
        schema = ExecCMDNodeSchema(
            node_proto_id=1,
            private_ip="192.168.1.1",
            api_port=8080,
            cmd="ls -la"
        )
        assert schema.cmd == "ls -la"
    
    def test_allow_df_command(self):
        """Разрешена команда df -h"""
        schema = ExecCMDNodeSchema(
            node_proto_id=1,
            private_ip="192.168.1.1",
            api_port=8080,
            cmd="df -h"
        )
        assert schema.cmd == "df -h"
    
    def test_allow_ps_command(self):
        """Разрешена команда ps aux"""
        schema = ExecCMDNodeSchema(
            node_proto_id=1,
            private_ip="192.168.1.1",
            api_port=8080,
            cmd="ps aux"
        )
        assert schema.cmd == "ps aux"
    
    def test_allow_sudo_systemctl(self):
        """Разрешена команда с sudo (sudo исключается из валидации)"""
        schema = ExecCMDNodeSchema(
            node_proto_id=1,
            private_ip="192.168.1.1",
            api_port=8080,
            cmd="sudo systemctl status"
        )
        assert schema.cmd == "sudo systemctl status"
    
    def test_allow_systemctl_without_sudo(self):
        """Разрешена команда systemctl без sudo"""
        schema = ExecCMDNodeSchema(
            node_proto_id=1,
            private_ip="192.168.1.1",
            api_port=8080,
            cmd="systemctl restart nginx"
        )
        assert schema.cmd == "systemctl restart nginx"
    
    def test_allow_cat_command(self):
        """Разрешена команда cat для чтения файлов"""
        schema = ExecCMDNodeSchema(
            node_proto_id=1,
            private_ip="192.168.1.1",
            api_port=8080,
            cmd="cat /var/log/app.log"
        )
        assert schema.cmd == "cat /var/log/app.log"
    
    def test_allow_grep_command(self):
        """Разрешена команда grep"""
        schema = ExecCMDNodeSchema(
            node_proto_id=1,
            private_ip="192.168.1.1",
            api_port=8080,
            cmd="grep error app.log"
        )
        assert schema.cmd == "grep error app.log"


class TestEdgeCases:
    """Тесты edge cases и граничных условий"""
    
    def test_command_exactly_two_chars(self):
        """Команда ровно 2 символа (граница min_length) - должна пройти"""
        schema = ExecCMDNodeSchema(
            node_proto_id=1,
            private_ip="192.168.1.1",
            api_port=8080,
            cmd="ls"  # Ровно 2 символа - минимум
        )
        assert schema.cmd == "ls"
    
    def test_command_with_multiple_spaces(self):
        """Команда с несколькими пробелами"""
        schema = ExecCMDNodeSchema(
            node_proto_id=1,
            private_ip="192.168.1.1",
            api_port=8080,
            cmd="ls    -la"  # Несколько пробелов
        )
        assert schema.cmd == "ls    -la"
    
    def test_command_with_leading_trailing_spaces(self):
        """Команда с ведущими и завершающими пробелами"""
        # Pydantic не триммит пробелы автоматически, поэтому команда с пробелами проходит
        schema = ExecCMDNodeSchema(
            node_proto_id=1,
            private_ip="192.168.1.1",
            api_port=8080,
            cmd="  ls -la  "  # Пробелы в начале и конце
        )
        assert schema.cmd == "  ls -la  "
    
    def test_ipv6_address(self):
        """Поддержка IPv6 адреса (IPvAnyAddress)"""
        schema = ExecCMDNodeSchema(
            node_proto_id=1,
            private_ip="2001:0db8:85a3:0000:0000:8a2e:0370:7334",
            api_port=8080,
            cmd="ls -la"
        )
        assert schema.private_ip == "2001:0db8:85a3:0000:0000:8a2e:0370:7334" or schema.private_ip == "2001:db8:85a3::8a2e:370:7334"
    
    def test_private_ip_conversion_to_string(self):
        """private_ip конвертируется в строку через field_validator"""
        schema = ExecCMDNodeSchema(
            node_proto_id=1,
            private_ip="192.168.1.1",
            api_port=8080,
            cmd="ls -la"
        )
        assert isinstance(schema.private_ip, str)
        assert schema.private_ip == "192.168.1.1"
