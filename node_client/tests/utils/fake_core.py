"""
Моки для эмуляции VPN ядер (xray, hysteria2, etc.)
"""
import subprocess
from dataclasses import dataclass
from typing import Optional
from unittest.mock import MagicMock


@dataclass
class FakeSubprocessResult:
    """
    Фейковый результат выполнения subprocess.run()
    
    Имитирует subprocess.CompletedProcess
    """
    returncode: int
    stdout: str
    stderr: str
    
    def __repr__(self):
        return f"FakeSubprocessResult(returncode={self.returncode}, stdout='{self.stdout[:50]}...', stderr='{self.stderr[:50]}...')"


def create_mock_subprocess(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
    raise_timeout: bool = False,
    raise_exception: Optional[Exception] = None
) -> MagicMock:
    """
    Создаёт мок для subprocess.run()
    
    Args:
        returncode: Код возврата команды (0 = успех)
        stdout: Содержимое stdout
        stderr: Содержимое stderr
        raise_timeout: Выбросить TimeoutExpired исключение
        raise_exception: Выбросить кастомное исключение
    
    Returns:
        MagicMock: Мок функции subprocess.run
    
    Example:
        >>> mock = create_mock_subprocess(returncode=0, stdout="Success")
        >>> result = mock("echo test", shell=True)
        >>> result.returncode
        0
    """
    mock = MagicMock()
    
    if raise_timeout:
        mock.side_effect = subprocess.TimeoutExpired(cmd="test_command", timeout=30)
    elif raise_exception:
        mock.side_effect = raise_exception
    else:
        mock.return_value = FakeSubprocessResult(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr
        )
    
    return mock


def create_xray_stats_output(users: list[dict]) -> str:
    """
    Создаёт фейковый вывод команды xray api statsquery
    
    Args:
        users: Список пользователей с email
    
    Returns:
        str: Строка в формате xray stats
    
    Example:
        >>> users = [{"email": "test1"}, {"email": "test2"}]
        >>> output = create_xray_stats_output(users)
        >>> "user>>>test1>>>traffic>>>uplink" in output
        True
    """
    lines = []
    for user in users:
        email = user.get("email", "unknown")
        # Имитируем формат xray stats
        lines.append(f'stat: <name:"user>>>{email}>>>traffic>>>uplink" value:1048576 >')
        lines.append(f'stat: <name:"user>>>{email}>>>traffic>>>downlink" value:2097152 >')
    
    return "\n".join(lines)


def create_xray_add_user_success() -> str:
    """Фейковый успешный ответ добавления пользователя"""
    return "User added successfully"


def create_xray_delete_user_success() -> str:
    """Фейковый успешный ответ удаления пользователя"""
    return "User removed successfully"


def create_reload_core_success() -> str:
    """Фейковый успешный ответ перезагрузки ядра"""
    return "Core reloaded successfully"


class FakeXrayCore:
    """
    Фейковое ядро xray для тестов
    
    Хранит список пользователей в памяти и имитирует операции
    """
    
    def __init__(self):
        self.users: dict[str, dict] = {}  # {email: user_obj}
        self.reload_count = 0
    
    def add_user(self, user_obj: dict) -> tuple[bool, str]:
        """Добавляет пользователя"""
        email = user_obj.get("email")
        if not email:
            return False, "Email not found in user object"
        
        self.users[email] = user_obj
        return True, f"User {email} added"
    
    def delete_user(self, email: str) -> tuple[bool, str]:
        """Удаляет пользователя"""
        if email in self.users:
            del self.users[email]
            return True, f"User {email} deleted"
        return True, f"User {email} not found (already deleted)"
    
    def get_user(self, email: str) -> Optional[dict]:
        """Получает пользователя"""
        return self.users.get(email)
    
    def reload(self) -> tuple[bool, str]:
        """Имитирует перезагрузку ядра"""
        self.reload_count += 1
        return True, f"Core reloaded (count: {self.reload_count})"
    
    def get_stats(self) -> str:
        """Получает статистику пользователей"""
        return create_xray_stats_output(list(self.users.values()))
