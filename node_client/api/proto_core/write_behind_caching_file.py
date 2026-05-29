"""
Write-Behind Caching для батчинга операций с конфиг-файлами протоколов
"""
import asyncio
import os
import time
from contextlib import asynccontextmanager
from typing import Annotated

import aiofiles
import orjson
from fastapi.params import Depends
from starlette.requests import Request

from node_client.config import TMP_DIR
from node_client.logger_config import log_event


class ConfigWriteBuffer:
    """
    Глобальный менеджер write-behind кэширования для всех виртуальных нод
    
    Архитектура:
    - Один экземпляр на всё приложение
    - Отдельный буфер для каждой виртуальной ноды
    - Отдельный воркер для каждой ноды (изоляция)
    - Динамическая регистрация нод при первом обращении
    """
    
    def __init__(self, max_batch: int = 5, timeout: float = 10.0):
        """
        Args:
            max_batch: Максимум операций в батче (на каждую ноду)
            timeout: Таймаут принудительной записи в секундах
        """
        self.max_batch = max_batch
        self.timeout = timeout
        
        # Хранилище пользователей {node_proto_id: {uuid: user_obj}}
        self.buffer_storage: dict[int, dict[str, dict]] = {}
        
        # Метаданные нод {node_proto_id: {filepath, users_path, reload_command}}
        self.node_metadata: dict[int, dict] = {}
        
        # Очереди операций для каждой ноды {node_proto_id: Queue}
        self.node_queues: dict[int, asyncio.Queue] = {}
        
        # Воркеры для каждой ноды {node_proto_id: Task}
        self.worker_tasks: dict[int, asyncio.Task] = {}

        # Флаг для выключения лимитов
        self.queue_limited = True


    async def register_node(
            self, node_proto_id: int, filepath: str, users_path: str,  flatten_user_identifier_key: str, reload_command: str | None, user_obj: dict | None = None
    ):
        """
        Регистрирует виртуальную ноду в менеджере
        
        Выполняет:
        0. Валидацию метаданных для управления очередью
        1. Сохранение метаданных
        2. Создание очереди
        3. Загрузку существующих пользователей из конфиг-файла
        4. Запуск воркера
        
        Args:
            node_proto_id: ID виртуальной ноды
            filepath: Путь к конфиг-файлу
            users_path: Flatten-json путь до массива clients
            flatten_user_identifier_key: Flatten-json путь до идентификатора пользователя
            reload_command: Команда перезагрузки ядра (если нет hot-reload)
            user_obj: Объект для валидации flatten_user_identifier_key
        """
        # 0. Проверяем значения перед сохранением
        try:
            # Проверка существования файла-конфига
            file_content = await self._read_config(filepath)

            # Проверка работоспособности ключа списка пользователей в файле
            users_list = self._navigate_to_path(file_content, users_path)

            # Проверка работоспособности ключа к пользовательскому объекту
            user_key_check = flatten_key2value(
                # user_obj - если вызов из add, users_list[0] - если из delete
                # Проблема в том, что удаление могут вызвать при пустом списке пользователей => нужна заглушка
                user_obj or (users_list[0] if users_list else {'success': Exception}),
                flatten_user_identifier_key
            )
            if user_key_check is Exception:
                raise KeyError(f'{flatten_user_identifier_key} не найден в user_obj')

        except Exception as e:
            log_event(f'\033[35m[Worker]\033[0m Валидация параметров перед регистрацией провалилась | error: \033[34m{e}\033[0m', level='ERROR')
            return False, e

        # 1. Сохраняем метаданные
        self.node_metadata[node_proto_id] = {
            'filepath': filepath,
            'users_path': users_path,
            'flatten_user_identifier_key': flatten_user_identifier_key,
            'reload_command': reload_command,
        }
        
        # 2. Создаём очередь
        self.node_queues[node_proto_id] = asyncio.Queue()
        
        # 3. Загружаем существующих пользователей из файла
        await self._load_users_from_config(node_proto_id)
        
        # 4. Запускаем воркер для этой ноды
        task = asyncio.create_task(self._node_worker(node_proto_id))
        self.worker_tasks[node_proto_id] = task
        
        log_event(f"Нода зарегистрирована | node_proto_id: \033[33m{node_proto_id}\033[0m | users_len: \033[32m{len(self.buffer_storage[node_proto_id])}\033[0m")
        return True, f'Зарегистрирована очередь | node_proto_id: \033[32m{node_proto_id}\033[0m'


    async def add_user(
        self, 
        node_proto_id: int,
        user_obj: dict,
        filepath: str | None = None,
        users_path: str | None = None,
        reload_command: str | None = None,
        flatten_user_identifier_key: str | None = None
    ):
        """
        Добавляет пользователя в буфер (O(1))
        
        Логика:
        1. Если пользователь УЖЕ в буфере → обновляем
        2. Если очередь существует → добавляем
        3. Если очереди нет → регистрируем ноду + добавляем
        
        Args:
            node_proto_id: ID виртуальной ноды
            uuid: UUID пользователя
            user_obj: Объект пользователя
            filepath: Путь к конфиг-файлу (нужен только при первом обращении)
            users_path: Flatten-json путь (нужен только при первом обращении)
            reload_command: Команда перезагрузки (нужна только при первом обращении)
            flatten_user_identifier_key: Flatten-json путь для формирования O(1) структуры пользователей в памяти
        """
        # Сценарий 1: Пользователь УЖЕ в буфере
        uuid = flatten_key2value(user_obj, flatten_user_identifier_key)
        if node_proto_id in self.buffer_storage and uuid in self.buffer_storage[node_proto_id]:
            log_event(f"Пользователь УЖЕ в буфере | node_proto_id: \033[35m{node_proto_id}\033[0m | uuid: \033[32m{uuid}\033[0m")

            "Опциональный апдейт пользователя в ядре"
            # self.buffer_storage[node_proto_id][uuid] = user_obj
            # await self.node_queues[node_proto_id].put({'op': 'update', 'uuid': uuid})
            return True, 'Пользователь добавлен'

        # Сценарий 2: Очередь существует, пользователя нет
        if node_proto_id in self.node_queues:
            log_event(f"Добавление пользователя | node_proto_id: \033[32m{node_proto_id}\033[0m | uuid: \033[33m{uuid}\033[0m")
            self.buffer_storage[node_proto_id][uuid] = user_obj
            await self.node_queues[node_proto_id].put({'op': 'add', 'uuid': uuid})
            return True, 'Пользователь добавлен'
        
        # Сценарий 3: Первое обращение к ноде
        if not all([filepath, users_path]):
            raise ValueError(
                f"При первом обращении к node_proto_id={node_proto_id} "
                f"нужны filepath и users_path"
            )
        
        # Регистрируем ноду (загружаем существующих пользователей)
        log_event(f"Первое обращение к ноде | node_proto_id: \033[35m{node_proto_id}\033[0m | регистрируем")
        reg_res, msg = await self.register_node(node_proto_id, filepath, users_path, flatten_user_identifier_key, reload_command, user_obj)
        if not reg_res:
            log_event(f'Не удалось зарегистрировать ноду | node_proto_id: \033[31m{node_proto_id}\033[0m', level='WARNING')
            return False, str(msg)
        
        # Добавляем нового пользователя
        self.buffer_storage[node_proto_id][uuid] = user_obj
        await self.node_queues[node_proto_id].put({'op': 'add', 'uuid': uuid})
        return True, 'Пользователь добавлен'


    async def delete_user(self, node_proto_id: int, uuid: str, filepath: str, users_path: str,  flatten_user_identifier_key: str, reload_command: str | None):
        """
        Удаляет пользователя из буфера (O(1))
        
        Args:
            node_proto_id: ID виртуальной ноды
            uuid: UUID пользователя
            filepath: Путь к конфиг-файлу
            users_path: Flatten-json путь до массива clients
            flatten_user_identifier_key: Flatten-json путь до идентификатора пользователя
            reload_command: Команда перезагрузки ядра (если нет hot-reload)
        """
        "Проверяем очередь node_proto_id в буфере"
        if node_proto_id not in self.buffer_storage:
            log_event(f"Попытка удаления из незарегистрированной ноды, пробуем подгрузить её | node_proto_id: \033[33m{node_proto_id}\033[0m", level='WARNING')
            reg_res, msg = await self.register_node(node_proto_id, filepath, users_path, flatten_user_identifier_key, reload_command)

            "Если нет, пытаемся зарегать"
            if not reg_res:
                log_event(f'Не удалось зарегистрировать ноду | node_proto_id: \033[31m{node_proto_id}\033[0m', level='WARNING')
                return False, str(msg)
        
        "Проверяем наличие пользователя"
        if not uuid in self.buffer_storage[node_proto_id]:
            log_event(f'Пользователя с uuid не существует в этом конфиге | uuid: \033[33m{uuid}\033[0m; config_file: \033[32m{filepath}\033[0m', level='WARNING')
            return True, 'Пользователя уже не было'

        "Удаляем из кэша и Добавляем в очередь"
        del self.buffer_storage[node_proto_id][uuid]
        log_event(f"Пользователь удалён из буфера | node_proto_id: \033[32m{node_proto_id}\033[0m | uuid: \033[32m{uuid}\033[0m")

        await self.node_queues[node_proto_id].put({'op': 'delete', 'uuid': uuid})
        return True, 'Пользователь удалён'


    async def stop(self):
        """Останавливает все воркеры и сбрасывает остатки на диск"""
        log_event("Остановка ConfigWriteBuffer...")
        
        "Останавливаем воркеры"
        for node_id, task in self.worker_tasks.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        "Сбрасываем остатки на диск"
        for node_id in self.node_metadata:
            if not self.node_queues[node_id].empty():
                log_event(f"Сброс остатков для node_proto_id: \033[33m{node_id}\033[0m")
                await self._write_node_to_disk(node_id)
        
        log_event("ConfigWriteBuffer остановлен")


    async def _load_users_from_config(self, node_id: int):
        """
        Загружает существующих пользователей из конфиг-файла в память
        
        Создаёт маппинг {uuid: user_obj} для O(1) операций
        """
        metadata = self.node_metadata[node_id]
        
        try:
            # Читаем конфиг
            config = await self._read_config(metadata['filepath'])
            
            # Получаем массив clients
            clients_array = self._navigate_to_path(config, metadata['users_path'])
            
            # Создаём маппинг {uuid: user_obj}
            self.buffer_storage[node_id] = {}
            for user_obj in clients_array:
                # Парсим flatten ключ к user_identifier, составляем пару {user_identifier: user_obj}
                user_identifier_value = flatten_key2value(user_obj, metadata['flatten_user_identifier_key'])
                self.buffer_storage[node_id][user_identifier_value] = user_obj
            
            log_event(f"Загружено пользователей из конфига | node_proto_id: \033[32m{node_id}\033[0m; count: \033[32m{len(self.buffer_storage[node_id])}\033[0m")
            
        except Exception as e:
            log_event(f"Ошибка загрузки пользователей из конфига | node_proto_id: \033[31m{node_id}\033[0m; error: \033[34m{e}\033[0m", level='ERROR')
            # Продолжаем с пустым буфером
            self.buffer_storage[node_id] = {}

    
    async def _node_worker(self, node_id: int):
        """
        Воркер для конкретной ноды
        
        Логика:
        - Ждёт timeout секунд или пока очередь не заполнится до max_batch
        - Если очередь >= max_batch → пишет сразу
        - Если таймаут истёк и очередь не пуста → пишет
        """
        while True:
            try:
                operations = []
                start_time = time.time()
                # 1. Запоминаем, состояние лимита на очередь перед сборкой батча
                was_limited = self.queue_limited

                # Собираем батч операций
                while len(operations) < self.max_batch:
                    remaining_time = self.timeout - (time.time() - start_time)
                    
                    # Если таймаут истёк
                    if remaining_time <= 0:
                        break
                    
                    try:
                        # Пытаемся забрать операцию с таймаутом
                        op = await asyncio.wait_for(
                            self.node_queues[node_id].get(),
                            timeout=remaining_time
                        )
                        operations.append(op)
                        self.node_queues[node_id].task_done()
                        
                    except asyncio.TimeoutError:
                        # Таймаут истёк, выходим
                        break

                # Если очередь ограничивается лимитами
                # Если есть операции → пишем на диск (неблокирующе)
                if was_limited and self.queue_limited and operations:
                    log_event(f"\033[35m[Worker]\033[0m Батч собран | node_proto_id: \033[32m{node_id}\033[0m; opers_len: \033[35m{len(operations)}\033[0m")
                    asyncio.create_task(self._write_node_to_disk(node_id))
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                log_event(f"\033[35m[Worker]\033[0m Ошибка воркера | node_proto_id: \033[31m{node_id}; error: \033[34m{e}\033[0m", level='CRITICAL')


    async def _write_node_to_disk(self, node_id: int):
        """
        Записывает текущее состояние буфера в конфиг-файл
        
        НЕ читаем конфиг для получения пользователей - используем буфер!
        """
        metadata = self.node_metadata[node_id]
        
        try:
            log_event(f"\033[34m[Write]\033[0m Запись на диск | node_proto_id: \033[32m{node_id}\033[0m | users: \033[34m{len(self.buffer_storage[node_id])}\033[0m")
            
            # 1. Читаем конфиг (только для получения структуры)
            config = await self._read_config(metadata['filepath'])
            
            # 2. Получаем ссылку на массив clients
            clients_array = self._navigate_to_path(config, metadata['users_path'])
            
            # 3. Заменяем массив на актуальное состояние буфера. Фишка структуры O(1). Значения в словаре - готовые пользовательские объекты для ядра
            clients_array.clear()
            clients_array.extend(list(self.buffer_storage[node_id].values()))
            
            # 4. Атомарно записываем конфиг
            await self._write_config_atomic(metadata['filepath'], config)
            
            # 5. Перезагружаем ядро (если нужно)
            if metadata['reload_command']:
                await self._reload_core(metadata['reload_command'])
            
            log_event(f"\033[34m[Write]\033[0m Успешная запись | node_proto_id: \033[32m{node_id}\033[0m")
            
        except Exception as e:
            log_event(f"\033[34m[Write]\033[0m КРИТИЧЕСКАЯ ошибка записи | node_proto_id: \033[31m{node_id}\033[0m | error: \033[34m{e}\033[0m", level='CRITICAL')


    async def _reload_core(self, reload_command: str):
        """Выполняет команду перезагрузки ядра"""
        try:
            log_event(f'Выполнение команды перезагрузки: "\033[33m{reload_command}\033[0m"')
            
            process = await asyncio.create_subprocess_shell(
                reload_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                log_event("Ядро успешно перезагружено")
            else:
                log_event(f"Ошибка перезагрузки ядра: \033[31m{stderr.decode()}\033[0m", level='CRITICAL')
                
        except Exception as e:
            log_event(f"Исключение при перезагрузке ядра | error: \033[34m{e}\033[0m", level='CRITICAL')

    @asynccontextmanager
    async def unlimit_queue(self, node_proto_id: int):
        """Временно отключает лимиты очереди для bulk операций"""
        self.queue_limited = False
        try:
            yield self
        finally:
            # Принудительно записываем все накопленные операции на диск
            await self._flush_all_nodes(node_proto_id)

    async def _flush_all_nodes(self, node_proto_id: int):
        """Принудительно записывает все ноды на диск (для bulk операций)"""
        log_event(f"\033[35m[Flush]\033[0m Принудительная запись конфиг-файла на инстансе ядра | node_proto_id: \033[33m{node_proto_id}\033[0m")
        await self._write_node_to_disk(node_proto_id)
        self.queue_limited = True



    # ========== Утилиты для работы с конфиг-файлами ==========
    
    @staticmethod
    async def _read_config(filepath: str) -> dict:
        """Читает конфиг-файл"""
        try:
            async with aiofiles.open(filepath, mode='r', encoding='utf-8') as f:
                content = await f.read()
                return orjson.loads(content)
        except FileNotFoundError:
            log_event(f'Конфиг-файл не найден: "\033[31m{filepath}\033[0m"', level='ERROR')
            raise
        except orjson.JSONDecodeError as e:
            log_event(f'Ошибка парсинга JSON в "\033[31m{filepath}\033[0m"; error: \033[34m{e}\033[0m', level='ERROR')
            raise
    
    @staticmethod
    async def _write_config_atomic(filepath: str, config_dict: dict):
        """Атомарная запись конфига через временный файл"""
        now = time.monotonic()

        # Используем только имя файла
        filename = os.path.basename(filepath)
        tmp_filepath = TMP_DIR / f"{filename}.{now}.tmp"

        try:
            # 1. Пишем во временный файл
            async with aiofiles.open(tmp_filepath, mode='wb') as f:
                json_bytes = orjson.dumps(config_dict, option=orjson.OPT_INDENT_2)
                await f.write(json_bytes)
            
            # 2. Атомарно подменяем старый файл новым. mv в POSIX - один такт процессорного времени, - либо да, либо нет
            os.replace(str(tmp_filepath), filepath)
            log_event(f"Конфиг атомарно обновлён: \033[33m{filepath}\033[0m")
            
        except Exception as e:
            log_event(f'Ошибка атомарной записи "\033[35m{filepath}\033[0m"; error: \033[34m{e}\033[0m', level='CRITICAL')
            # Удаляем временный файл при ошибке
            if tmp_filepath.exists():
                tmp_filepath.unlink()
            raise

    @staticmethod
    def _navigate_to_path(config: dict, flatten_path: str) -> list:
        """
        Навигация по flatten-json пути до массива
        
        Args:
            config: Конфиг-словарь
            flatten_path: Путь типа "inbounds___1___settings___clients"
            
        Returns:
            list: Ссылка на массив пользователей
        """
        current = flatten_key2value(config, flatten_path)
        if not isinstance(current, list):
            raise TypeError(f"Путь '{flatten_path}' не указывает на массив")
        
        return current


def flatten_key2value(
        json_obj: dict, flatten_key: str, new_last_obj: dict = None, replace_last_obj: bool = False, delete_obj: bool = False
):
    """
    Ультимативная функция для парсинга flatten-json ключей
    1. Может просто возращать конечное значение
    2. Удалять последний объект по ключу
    3. Подменять последний объект

    Exception используется в качестве Fallback для гарантированного понимания "Мы точно не нашли объект по ключу"

    :param json_obj: Исходный json
    :param flatten_key: flatten-json ключ-строка
    :param new_last_obj: Если нужна подмена, новый объект взамен старого
    :param replace_last_obj: Флаг для подмены
    :param delete_obj: Флаг для удаления последнего объекта
    :return:
    """
    keys = flatten_key.split('___')
    current = json_obj

    for idx, key in enumerate(keys):
        # Пытаемся преобразовать в int (для индексов массивов)
        if key.isdigit():
            key = int(key)

        # Исполняем операцию над последним объектом по flatten ключу. Изменения отобразятся в исходном json_obj
        if idx == len(keys) - 1:
            # Удаляем объект
            if delete_obj:
                # Если ключ - индекс в массиве
                del current[key]
                return None
            # Подменяем содержимое
            if replace_last_obj and new_last_obj is not None:
                current[key] = new_last_obj
                return None


        # Простой select. Продвигаемся дальше
        try:
            current = current[key]
        except (ValueError, TypeError):
            current = current.get(key, Exception)

        # Ранний выход, если ключ не найден
        if current is Exception:
            return Exception

    return current


def get_proto_cores_buffer(request: Request):
    return request.app.state.core_buffer

CoreBuffersDep = Annotated[ConfigWriteBuffer, Depends(get_proto_cores_buffer)]