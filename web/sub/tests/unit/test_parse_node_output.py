"""
Unit тесты для parse_node_output — функции выполнения пользовательских парсеров метрик.

parse_node_output создаёт изолированное окружение для выполнения динамического кода,
который парсит ответ ноды (stdout команды или результат скрипта API).

Новая сигнатура: (success: bool, (data, troubles): tuple, message: str)
"""
import pytest

from web.sub.arq_tasks.metrics_collector import parse_node_output

# Отключаем autouse фикстуры для unit тестов
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.usefixtures()  # Пустой usefixtures чтобы отключить db_seed
]


class TestParseNodeOutput:
    """Unit тесты для parse_node_output"""
    
    async def test_parse_simple_sync_parser(self):
        """
        Простой синхронный парсер возвращает список пользователей.
        """
        # Arrange: простой парсер-скрипт
        script = """
def parse(data):
    # Простой парсинг: разделяем строки и извлекаем данные
    lines = data.strip().split('\\n')
    result = []
    for line in lines:
        if '|' in line:
            username, traffic = line.split('|')
            result.append({
                'tg_username': username.strip(),
                'total_mb_used': int(traffic.strip())
            })
    return result, []
"""
        
        stdout = """
user1@test.com | 100
user2@test.com | 250
"""
        
        # Act
        success, (data, troubles), message = await parse_node_output(script, stdout, None)
        
        # Assert
        assert success is True
        assert data is not None
        assert troubles == []
        assert len(data) == 2
        assert data[0]['tg_username'] == 'user1@test.com'
        assert data[0]['total_mb_used'] == 100
        assert data[1]['tg_username'] == 'user2@test.com'
        assert data[1]['total_mb_used'] == 250
        assert 'Успешно' in message
    
    
    async def test_parse_async_parser(self):
        """
        Асинхронный парсер (async def parse) автоматически awaited.
        """
        # Arrange: async парсер
        script = """
async def parse(data):
    # Имитация async парсинга
    lines = data.strip().split('\\n')
    return [{'tg_username': line, 'total_mb_used': 50} for line in lines if line], []
"""
        
        stdout = "user1@test.com\nuser2@test.com"
        
        # Act
        success, (data, troubles), message = await parse_node_output(script, stdout, None)
        
        # Assert
        assert success is True
        assert data is not None
        assert len(data) == 2
        assert data[0]['tg_username'] == 'user1@test.com'
    
    
    async def test_parse_with_user_libraries(self):
        """
        Парсер использует доступные библиотеки из global_scope.
        
        json и re доступны напрямую без import.
        """
        # Arrange: парсер использует json и re из global_scope
        script = """
def parse(data):
    # json и re доступны из global_scope
    # Парсим JSON и фильтруем через regex
    data_dict = json.loads(data)
    users = data_dict.get('users', [])
    
    result = []
    for user in users:
        # Извлекаем email через regex
        match = re.match(r'(.+)@.+', user['email'])
        if match:
            result.append({
                'tg_username': user['email'],
                'total_mb_used': user['traffic']
            })
    return result, []
"""
        
        stdout = '{"users": [{"email": "user1@test.com", "traffic": 100}, {"email": "user2@test.com", "traffic": 200}]}'
        
        # Act
        success, (data, troubles), message = await parse_node_output(script, stdout, None)
        
        # Assert
        assert success is True
        assert data is not None
        assert len(data) == 2
        assert data[0]['tg_username'] == 'user1@test.com'
        assert data[0]['total_mb_used'] == 100
    
    
    async def test_parse_function_not_found(self):
        """
        Скрипт не содержит функцию parse — возвращает ошибку.
        """
        # Arrange: скрипт БЕЗ функции parse
        script = """
def some_other_function():
    return "hello"
"""
        
        # Act
        success, (data, troubles), message = await parse_node_output(script, "test data", None)
        
        # Assert
        assert success is False
        assert data is None
        assert troubles is None
        assert "функция parse не найдена в скрипте!" in message
    
    
    async def test_parse_import_error(self):
        """
        Библиотека не найдена — возвращает ImportError.
        """
        # Arrange
        script = """
def parse(data):
    return [], []
"""
        
        # Act: пытаемся импортировать несуществующую библиотеку
        success, (data, troubles), message = await parse_node_output(script, "test", "non_existent_library_xyz")
        
        # Assert
        assert success is False
        assert data is None
        assert troubles is None
        assert "Библиотека" in message
        assert "не найдена" in message
    
    
    async def test_parse_execution_error(self):
        """
        Ошибка выполнения скрипта (runtime error).
        """
        # Arrange: скрипт с ошибкой
        script = """
def parse(data):
    # Пытаемся разделить на ноль
    result = 1 / 0
    return result
"""
        
        # Act
        success, (data, troubles), message = await parse_node_output(script, "test", None)
        
        # Assert
        assert success is False
        assert data is None
        assert troubles is None
        assert "Ошибка выполнения скрипта" in message
        assert "ZeroDivisionError" in message
    
    
    async def test_parse_syntax_error(self):
        """
        Синтаксическая ошибка в скрипте.
        """
        # Arrange: скрипт с синтаксической ошибкой
        script = """
def parse(data):
    if True
        return []
"""
        
        # Act
        success, (data, troubles), message = await parse_node_output(script, "test", None)
        
        # Assert
        assert success is False
        assert data is None
        assert troubles is None
        assert "Синтаксическая ошибка в скрипте" in message
    
    
    async def test_parse_security_restrictions(self):
        """
        Проверяем изоляцию: запрещённые функции недоступны.
        
        Скрипт пытается использовать open, eval, __import__.
        """
        # Arrange: скрипт пытается использовать open
        script_open = """
def parse(data):
    with open('/etc/passwd', 'r') as f:
        content = f.read()
    return [], []
"""
        
        # Act
        success, (data, troubles), message = await parse_node_output(script_open, "test", None)
        
        # Assert: должна быть ошибка (open недоступен)
        assert success is False
        assert data is None
        assert troubles is None
        assert message is not None
        
        # Arrange: скрипт пытается использовать eval
        script_eval = """
def parse(data):
    eval('print("hack")')
    return [], []
"""
        
        # Act
        success, (data, troubles), message = await parse_node_output(script_eval, "test", None)
        
        # Assert: должна быть ошибка (eval недоступен)
        assert success is False
        assert data is None
        assert troubles is None
    
    
    async def test_parse_empty_result(self):
        """
        Парсер возвращает пустой список (нет данных).
        """
        # Arrange
        script = """
def parse(data):
    return [], []
"""
        
        # Act
        success, (data, troubles), message = await parse_node_output(script, "empty", None)
        
        # Assert
        assert success is True
        assert data == []
        assert troubles == []


class TestParseNodeOutputRealParser:
    """Тесты с реальным xray парсером из БД"""
    
    async def test_real_xray_parser_json_dict(self, db_pool, real_parser_scripts, sample_xray_outputs):
        """
        Реальный парсер обрабатывает JSON dict от xtlsapi.
        """
        # Arrange
        parser = real_parser_scripts['vless_tcp_sni_based']
        stdout = sample_xray_outputs['json_dict_clean']
        
        # Act
        success, (data, troubles), message = await parse_node_output(
            parser['metrics_parser_code'],
            stdout,
            parser['sub_required_libs']
        )
        
        # Assert
        assert success is True
        assert data is not None
        assert len(data) == 2  # alice + bob
        
        # Проверяем alice: 100MB + 50MB = 150MB
        alice = next(u for u in data if u['tg_username'] == 'alice@example.com')
        assert alice['total_mb_used'] == 150
        
        # Проверяем bob: 200MB + 100MB = 300MB
        bob = next(u for u in data if u['tg_username'] == 'bob@example.com')
        assert bob['total_mb_used'] == 300
    
    
    async def test_real_xray_parser_json_string_cli(self, db_pool, real_parser_scripts, sample_xray_outputs):
        """
        Реальный парсер обрабатывает JSON string от CLI команды.
        
        Важно: первая запись mvpALXI имеет отсутствующее поле value (downlink),
        но есть uplink с большим значением.
        """
        # Arrange
        parser = real_parser_scripts['vless_tcp_sni_based']
        stdout = sample_xray_outputs['json_string_from_cli']
        
        # Act
        success, (data, troubles), message = await parse_node_output(
            parser['metrics_parser_code'],
            stdout,
            parser['sub_required_libs']
        )
        
        # Assert
        assert success is True
        assert data is not None
        assert len(data) == 2  # mvpALXI + TestAddUser1
        
        # Проверяем mvpALXI: downlink нет value (0), uplink = 3331331376938 bytes
        mvp = next(u for u in data if u['tg_username'] == 'mvpALXI')
        assert mvp['total_mb_used'] > 0  # ~3176 MB
        
        # Проверяем TestAddUser1: downlink + uplink
        test_user = next(u for u in data if u['tg_username'] == 'TestAddUser1')
        assert test_user['total_mb_used'] > 0
    
    
    async def test_real_xray_parser_with_troubles(self, db_pool, real_parser_scripts, sample_xray_outputs):
        """
        Реальный парсер обрабатывает данные с невалидными записями.
        
        Записи без "user>>>" префикса попадают в troubles.
        Записи без value обрабатываются как 0 bytes.
        """
        # Arrange
        parser = real_parser_scripts['vless_tcp_sni_based']
        stdout = sample_xray_outputs['with_troubles']
        
        # Act
        success, (data, troubles), message = await parse_node_output(
            parser['metrics_parser_code'],
            stdout,
            parser['sub_required_libs']
        )
        
        # Assert
        assert success is True
        assert data is not None
        assert troubles is not None
        
        # Валидные записи (включая another@example.com с value=0)
        assert len(data) == 2
        valid = next(u for u in data if u['tg_username'] == 'valid@example.com')
        assert valid['total_mb_used'] == 100
        
        another = next(u for u in data if u['tg_username'] == 'another@example.com')
        assert another['total_mb_used'] == 0  # Нет value -> 0 bytes
        
        # Проблемные записи (только без "user>>>" префикса)
        assert len(troubles) == 1
    
    
    async def test_real_xray_parser_empty_stats(self, db_pool, real_parser_scripts, sample_xray_outputs):
        """
        Реальный парсер обрабатывает пустой список статистики.
        """
        # Arrange
        parser = real_parser_scripts['vless_tcp_sni_based']
        stdout = sample_xray_outputs['empty_stats']
        
        # Act
        success, (data, troubles), message = await parse_node_output(
            parser['metrics_parser_code'],
            stdout,
            parser['sub_required_libs']
        )
        
        # Assert
        assert success is True
        assert data == []
        assert troubles == []
