"""
Write-Behind Caching для батчинга операций с конфиг-файлами протоколов
"""
import asyncio
import time
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


    async def register_node(
            self, node_proto_id: int, filepath: str, users_path: str,  flatten_user_identifier_key: str, reload_command: str | None
    ):
        """
        Регистрирует виртуальную ноду в менеджере
        
        Выполняет:
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
        """
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
        
        log_event(f"Нода зарегистрирована | node_proto_id: {node_proto_id} | users: {len(self.buffer_storage[node_proto_id])}")


    async def add_user(
        self, 
        node_proto_id: int, 
        uuid: str, 
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
        if node_proto_id in self.buffer_storage and uuid in self.buffer_storage[node_proto_id]:
            log_event(f"Пользователь УЖЕ в буфере | node_proto_id: {node_proto_id} | uuid: {uuid}")

            "Опциональный апдейт пользователя в ядре"
            # self.buffer_storage[node_proto_id][uuid] = user_obj
            # await self.node_queues[node_proto_id].put({'op': 'update', 'uuid': uuid})
            return
        
        # Сценарий 2: Очередь существует, пользователя нет
        if node_proto_id in self.node_queues:
            log_event(f"Добавление пользователя | node_proto_id: {node_proto_id} | uuid: {uuid}")
            self.buffer_storage[node_proto_id][uuid] = user_obj
            await self.node_queues[node_proto_id].put({'op': 'add', 'uuid': uuid})
            return
        
        # Сценарий 3: Первое обращение к ноде
        if not all([filepath, users_path]):
            raise ValueError(
                f"При первом обращении к node_proto_id={node_proto_id} "
                f"нужны filepath и users_path"
            )
        
        # Регистрируем ноду (загружаем существующих пользователей)
        log_event(f"Первое обращение к ноде | node_proto_id: {node_proto_id} | регистрируем")
        await self.register_node(node_proto_id, filepath, users_path, flatten_user_identifier_key, reload_command)
        
        # Добавляем нового пользователя
        self.buffer_storage[node_proto_id][uuid] = user_obj
        await self.node_queues[node_proto_id].put({'op': 'add', 'uuid': uuid})


    async def delete_user(self, node_proto_id: int, uuid: str):
        """
        Удаляет пользователя из буфера (O(1))
        
        Args:
            node_proto_id: ID виртуальной ноды
            uuid: UUID пользователя
        """
        if node_proto_id not in self.buffer_storage:
            log_event(f"Попытка удаления из незарегистрированной ноды | node_proto_id: {node_proto_id}", level='WARNING')
            return
        
        # Удаляем из кэша
        if uuid in self.buffer_storage[node_proto_id]:
            del self.buffer_storage[node_proto_id][uuid]
            log_event(f"Пользователь удалён из буфера | node_proto_id: {node_proto_id} | uuid: {uuid}")
        
        # Добавляем в очередь
        await self.node_queues[node_proto_id].put({'op': 'delete', 'uuid': uuid})


    async def stop(self):
        """Останавливает все воркеры и сбрасывает остатки на диск"""
        log_event("Остановка ConfigWriteBuffer...", level='INFO')
        
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
                log_event(f"Сброс остатков для node_proto_id: {node_id}", level='INFO')
                await self._write_node_to_disk(node_id)
        
        log_event("ConfigWriteBuffer остановлен", level='INFO')


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
            
            log_event(f"Загружено пользователей из конфига | node_proto_id: {node_id} | count: {len(self.buffer_storage[node_id])}")
            
        except Exception as e:
            log_event(f"Ошибка загрузки пользователей из конфига | node_proto_id: {node_id} | error: {e}", level='ERROR')
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
                
                # Если есть операции → пишем на диск (неблокирующе)
                if operations:
                    log_event(f"[Worker] Батч собран | node_proto_id: {node_id} | operations: {len(operations)}")
                    asyncio.create_task(self._write_node_to_disk(node_id))
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                log_event(f"[Worker] Ошибка воркера | node_proto_id: {node_id} | error: {e}", level='CRITICAL')


    async def _write_node_to_disk(self, node_id: int):
        """
        Записывает текущее состояние буфера в конфиг-файл
        
        НЕ читаем конфиг для получения пользователей - используем буфер!
        """
        metadata = self.node_metadata[node_id]
        
        try:
            log_event(f"[Write] Запись на диск | node_proto_id: {node_id} | users: {len(self.buffer_storage[node_id])}")
            
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
            
            log_event(f"[Write] Успешная запись | node_proto_id: {node_id}")
            
        except Exception as e:
            log_event(f"[Write] КРИТИЧЕСКАЯ ошибка записи | node_proto_id: {node_id} | error: {e}", level='CRITICAL')


    async def _reload_core(self, reload_command: str):
        """Выполняет команду перезагрузки ядра"""
        try:
            log_event(f"Выполнение команды перезагрузки: {reload_command}", level='INFO')
            
            process = await asyncio.create_subprocess_shell(
                reload_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                log_event("Ядро успешно перезагружено", level='INFO')
            else:
                log_event(f"Ошибка перезагрузки ядра: {stderr.decode()}", level='CRITICAL')
                
        except Exception as e:
            log_event(f"Исключение при перезагрузке ядра: {e}", level='CRITICAL')


    # ========== Утилиты для работы с конфиг-файлами ==========
    
    @staticmethod
    async def _read_config(filepath: str) -> dict:
        """Читает конфиг-файл"""
        try:
            async with aiofiles.open(filepath, mode='r', encoding='utf-8') as f:
                content = await f.read()
                return orjson.loads(content)
        except FileNotFoundError:
            log_event(f"Конфиг-файл не найден: {filepath}", level='ERROR')
            raise
        except orjson.JSONDecodeError as e:
            log_event(f"Ошибка парсинга JSON в {filepath}: {e}", level='ERROR')
            raise
    
    @staticmethod
    async def _write_config_atomic(filepath: str, config_dict: dict):
        """Атомарная запись конфига через временный файл"""
        from datetime import datetime
        import os
        
        now = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        safe_filename = filepath.replace('/', '_').replace('\\', '_')
        tmp_filepath = TMP_DIR / f"{safe_filename}.{now}.tmp"
        
        try:
            # 1. Пишем во временный файл
            async with aiofiles.open(tmp_filepath, mode='wb') as f:
                json_bytes = orjson.dumps(config_dict, option=orjson.OPT_INDENT_2)
                await f.write(json_bytes)
            
            # 2. Атомарно подменяем старый файл новым. mv в POSIX - один такт процессорного времени, - либо да, либо нет
            os.replace(str(tmp_filepath), filepath)
            log_event(f"Конфиг атомарно обновлён: {filepath}", level='INFO')
            
        except Exception as e:
            log_event(f"Ошибка атомарной записи {filepath}: {e}", level='CRITICAL')
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
            raise TypeError(f"Путь {flatten_path} не указывает на массив")
        
        return current


def flatten_key2value(json_obj: dict, flatten_key: str):
    keys = flatten_key.split('___')
    current = json_obj

    for key in keys:
        # Пытаемся преобразовать в int (для индексов массивов)
        try:
            key_int = int(key)
            current = current[key_int]
        except (ValueError, TypeError):
            # Обычный ключ словаря
            current = current[key]

    return current


def get_proto_cores_buffer(request: Request):
    return request.app.state.core_buffers

CoreBuffersDep = Annotated[ConfigWriteBuffer, Depends(get_proto_cores_buffer)]