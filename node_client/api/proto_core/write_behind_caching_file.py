"""
Write-Behind Caching для батчинга операций с конфиг-файлами протоколов
"""

import asyncio
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Literal

import aiofiles
import orjson
from fastapi.params import Depends
from starlette.requests import Request

from node_client.api.sandbox.hot_reload_executor import HotReloadExecutor
from node_client.config import TMP_DIR, env
from node_client.exceptions import NodeInitError
from node_client.utils.logger_config import log_event


class ConfigWriteBuffer:
    """
    Глобальный менеджер write-behind кэширования для всех виртуальных нод

    Архитектура:
    - Один экземпляр на всё приложение
    - Отдельный буфер для каждой виртуальной ноды
    - Отдельный воркер для каждой ноды (изоляция)
    - Ноды регистрируются при старте и при реинициализации (данные из админки, /startup)
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

        # Локал стейт для инжекторов, скриптов сбора/парсинга метрик.
        # Переносное хранилище между изолированными окружениями скриптов
        self.local_state: dict[int, dict] = {}

        # Метаданные нод {node_proto_id: {filepath, users_path, reload_command, queue_limited}}
        self.node_metadata: dict[int, dict] = {}

        # Очереди операций для каждой ноды {node_proto_id: Queue}
        self.node_queues: dict[int, asyncio.Queue] = {}
        # Воркеры для каждой ноды {node_proto_id: Task}
        self.worker_tasks: dict[int, asyncio.Task] = {}
        # Активные задачи записи для каждой ноды {node_proto_id: set[Task]}
        self.pending_writes: dict[int, set[asyncio.Task]] = {}

    async def register_node(self, item: dict) -> None:
        """
        Регистрация/обновление одной виртуальной ноды: проверка, компиляция и применение метаданных

        Args:
            item: Словарь с полями VnodeServiceData

        Raises:
            NodeInitError: при ошибке валидации или компиляции (память нод-клиента не меняется)
        """
        metadata = await self.compile_node(item)
        await self.apply_nodes({item['node_proto_id']: metadata})

    async def compile_node(self, item: dict) -> dict:
        """
        Проверяет элемент ответа /startup и компилирует его RAW-скрипты. Память нод-клиента НЕ меняет.

        Выполняет:
        0. Валидацию метаданных
        1. Компиляцию RAW скриптов в скомпилированные функции
        2. Проверку, что конфиг читается, а курсоры user_injectors указывают на массивы

        Args:
            item: Словарь с полями VnodeServiceData

        Returns:
            dict: метаданные ноды для apply_nodes()

        Raises:
            NodeInitError: при ошибке валидации или компиляции
        """
        node_proto_id = item.get('node_proto_id')

        # 0. Валидация обязательных полей
        if not isinstance(node_proto_id, int) or node_proto_id <= 0:
            raise NodeInitError(node_proto_id, 'node_proto_id', 'должен быть int > 0')

        filepath = item.get('filepath')
        if not filepath or not isinstance(filepath, str):
            raise NodeInitError(node_proto_id, 'filepath', 'должен быть непустой строкой')

        user_injectors_raw = item.get('user_injectors', [])
        if not isinstance(user_injectors_raw, list):
            raise NodeInitError(node_proto_id, 'user_injectors', 'должен быть списком')

        # 1. Компиляция скриптов конвертеров
        conf_converter_libs = item.get('conf_converter_libs')
        proto_python_lib = item.get('proto_python_lib')

        try:
            config2json_script_raw = item.get('config2json_script')
            if config2json_script_raw is None:
                config_loader = lambda x: orjson.loads(x)  # noqa: E731
            else:
                config_loader = HotReloadExecutor.get_compiled_func(
                    config2json_script_raw, 'config2json', conf_converter_libs
                )
        except Exception as e:
            raise NodeInitError(node_proto_id, 'config2json_script', repr(e)) from e

        try:
            json2config_script_raw = item.get('json2config_script')
            if json2config_script_raw is None:
                config_dumper = lambda x: orjson.dumps(x, option=orjson.OPT_INDENT_2)  # noqa: E731
            else:
                config_dumper = HotReloadExecutor.get_compiled_func(
                    json2config_script_raw, 'json2config', conf_converter_libs
                )
        except Exception as e:
            raise NodeInitError(node_proto_id, 'json2config_script', repr(e)) from e

        # 2. Проверка конфиг-файла и user_injectors
        try:
            ok, file_content = await self._read_config(filepath, True)
            json_content = config_loader(file_content)
        except Exception as e:
            raise NodeInitError(node_proto_id, 'filepath', f'ошибка чтения/парсинга конфига: {repr(e)}') from e

        injectors = []
        for idx, inj in enumerate(user_injectors_raw):
            cursor = inj.get('flatten_array_cursor', '') if isinstance(inj, dict) else ''
            if not cursor:
                raise NodeInitError(
                    node_proto_id, f'user_injectors[{idx}].flatten_array_cursor', 'должен быть непустой строкой'
                )
            try:
                self._navigate_to_path(json_content, cursor)
            except Exception as e:
                raise NodeInitError(node_proto_id, f'user_injectors[{idx}].flatten_array_cursor', repr(e)) from e

            extractor_raw = inj.get('extractor_script')
            libs = inj.get('libs')
            try:
                if extractor_raw:
                    extractor_func = HotReloadExecutor.get_compiled_func(extractor_raw, 'transform', libs)
                else:
                    extractor_func = None
            except Exception as e:
                raise NodeInitError(node_proto_id, f'user_injectors[{idx}].extractor_script', repr(e)) from e

            injectors.append(
                {
                    'flatten_array_cursor': cursor,
                    'extractor_script': extractor_func,
                }
            )

        # 3. Компиляция скриптов API операций
        def _compile_optional(raw_script: str | None, func_name: str, field_name: str):
            """Компилирует необязательный скрипт, возвращает None если скрипт не задан"""
            if not raw_script:
                return None
            try:
                return HotReloadExecutor.get_compiled_func(raw_script, func_name, proto_python_lib)
            except Exception as e:
                raise NodeInitError(node_proto_id, field_name, repr(e)) from e

        # api_bulk_add_user_script: ищем 'bulk_add_users' или 'add_user'
        compiled_add_script = None
        add_script_raw = item.get('api_bulk_add_user_script')
        if add_script_raw:
            try:
                global_scope = HotReloadExecutor._prepare_globals(proto_python_lib)
                compiled_code = HotReloadExecutor._get_compiled_code(add_script_raw)
                exec(compiled_code, global_scope, global_scope)
                compiled_add_script = global_scope.get('bulk_add_users') or global_scope.get('add_user')
                if not compiled_add_script:
                    raise NodeInitError(
                        node_proto_id, 'api_bulk_add_user_script', 'функция bulk_add_users/add_user не найдена'
                    )
            except NodeInitError:
                raise
            except Exception as e:
                raise NodeInitError(node_proto_id, 'api_bulk_add_user_script', repr(e)) from e

        # api_bulk_delete_user_script: ищем 'bulk_delete_users' или 'delete_user'
        compiled_delete_script = None
        delete_script_raw = item.get('api_bulk_delete_user_script')
        if delete_script_raw:
            try:
                global_scope = HotReloadExecutor._prepare_globals(proto_python_lib)
                compiled_code = HotReloadExecutor._get_compiled_code(delete_script_raw)
                exec(compiled_code, global_scope, global_scope)
                compiled_delete_script = global_scope.get('bulk_delete_users') or global_scope.get('delete_user')
                if not compiled_delete_script:
                    raise NodeInitError(
                        node_proto_id, 'api_bulk_delete_user_script', 'функция bulk_delete_users/delete_user не найдена'
                    )
            except NodeInitError:
                raise
            except Exception as e:
                raise NodeInitError(node_proto_id, 'api_bulk_delete_user_script', repr(e)) from e

        compiled_metrics_script = _compile_optional(item.get('api_metrics_script'), 'get_metrics', 'api_metrics_script')
        compiled_parser = _compile_optional(item.get('metrics_parser_code'), 'parse_metrics', 'metrics_parser_code')

        # 4. Метаданные ноды (расширенная структура). В память их кладёт apply_nodes()
        return {
            'filepath': filepath,
            'config2json_script': config_loader,
            'json2config_script': config_dumper,
            'injectors': injectors,
            'reload_command': item.get('reload_command'),
            'api_bulk_add_user_script': compiled_add_script,
            'api_bulk_delete_user_script': compiled_delete_script,
            'api_metrics_script': compiled_metrics_script,
            'metrics_command': item.get('metrics_command'),
            'metrics_parser_code': compiled_parser,
            'proto_python_lib': proto_python_lib,
            'queue_limited': True,
        }

    async def apply_nodes(self, compiled: dict[int, dict]) -> None:
        """
        Применяет метаданные, заранее проверенные и скомпилированные через compile_node()

        1. Метаданные всех нод подменяются одним шагом, без await между ними: другие корутины
           не увидят половину обновления.
        2. Для новых нод создаются очередь, буфер пользователей, local_state и воркер.
           У известных нод buffer_storage, local_state и воркер не трогаются (требование 4.3).

        Args:
            compiled: {node_proto_id: метаданные из compile_node()}
        """
        new_ids = [node_proto_id for node_proto_id in compiled if node_proto_id not in self.node_metadata]

        for node_proto_id, metadata in compiled.items():
            old_metadata = self.node_metadata.get(node_proto_id)
            if old_metadata is not None:
                # bulk-операция могла прямо сейчас снять лимит очереди (unlimit_queue) — сохраняем режим
                metadata['queue_limited'] = old_metadata['queue_limited']
            self.node_metadata[node_proto_id] = metadata

        for node_proto_id in new_ids:
            self.node_queues[node_proto_id] = asyncio.Queue()
            self.pending_writes[node_proto_id] = set()
            await self._load_users_from_config(node_proto_id)
            self.local_state[node_proto_id] = {}
            self.worker_tasks[node_proto_id] = asyncio.create_task(self._node_worker(node_proto_id))
            await self._audit_state(node_proto_id)

        for node_proto_id in compiled:
            action_word = "зарегистрирована" if node_proto_id in new_ids else "обновлена"
            users_count = len(self.buffer_storage.get(node_proto_id, {}))
            log_event(
                f"Нода {action_word} | node_proto_id: \033[33m{node_proto_id}\033[0m | users_len: \033[32m{users_count}\033[0m"
            )

    async def remove_node(self, node_proto_id: int) -> None:
        """
        Полностью убирает виртуальную ноду из памяти нод-клиента (админка сообщила, что её больше нет)

        Сначала останавливается воркер и дожидаются начатые записи на диск: им ещё нужны метаданные.
        Остатки очереди на диск не сбрасываются — нода снята с учёта, её конфиг больше не ведём.
        """
        worker = self.worker_tasks.pop(node_proto_id, None)
        if worker is not None:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

        pending = list(self.pending_writes.get(node_proto_id, ()))
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        for storage in (
            self.node_metadata,
            self.node_queues,
            self.pending_writes,
            self.buffer_storage,
            self.local_state,
        ):
            storage.pop(node_proto_id, None)

        log_event(f"Нода удалена из памяти нод-клиента | node_proto_id: \033[33m{node_proto_id}\033[0m")

    def get_metadata(self, node_proto_id: int) -> dict:
        """
        Возвращает метаданные виртуальной ноды

        Args:
            node_proto_id: ID виртуальной ноды

        Returns:
            dict: метаданные ноды со скомпилированными функциями

        Raises:
            NodeNotRegisteredError: если нода не зарегистрирована
        """
        from node_client.exceptions import NodeNotRegisteredError

        meta = self.node_metadata.get(node_proto_id)
        if meta is None:
            raise NodeNotRegisteredError(node_proto_id)
        return meta

    def read_config_json(self, node_proto_id: int, text: str) -> dict:
        """Конвертирует текст конфига в JSON (dict) через скомпилированный config2json_script ноды"""
        meta = self.get_metadata(node_proto_id)
        loader = meta['config2json_script']
        return loader(text)

    def dump_config(self, node_proto_id: int, data: dict) -> bytes:
        """Конвертирует JSON-структуру в байты конфига через скомпилированный json2config_script ноды"""
        meta = self.get_metadata(node_proto_id)
        dumper = meta['json2config_script']
        res = dumper(data)
        if isinstance(res, str):
            return res.encode('utf-8')
        return res

    async def add_user(
        self,
        node_proto_id: int,
        user_obj: dict | str,
    ):
        """
        Добавляет пользователя в буфер (O(1))

        Args:
            node_proto_id: ID виртуальной ноды
            user_obj: Объект пользователя (или строка uuid)

        Raises:
            NodeNotRegisteredError: если нода не зарегистрирована
        """
        from node_client.exceptions import NodeNotRegisteredError

        if node_proto_id not in self.node_metadata:
            raise NodeNotRegisteredError(node_proto_id)

        uuid = user_obj['user_uuid'] if isinstance(user_obj, dict) else user_obj

        # Сценарий 1: Пользователь УЖЕ в буфере
        if node_proto_id in self.buffer_storage and uuid in self.buffer_storage[node_proto_id]:
            log_event(
                f"Пользователь УЖЕ в буфере | node_proto_id: \033[35m{node_proto_id}\033[0m | uuid: \033[32m{uuid}\033[0m"
            )
            return True, 200, 'Пользователь добавлен'

        # Сценарий 2: Очередь существует, пользователя нет
        if node_proto_id in self.node_queues:
            log_event(
                f"Добавление пользователя | node_proto_id: \033[32m{node_proto_id}\033[0m | uuid: \033[33m{uuid}\033[0m"
            )
            self.buffer_storage[node_proto_id][uuid] = user_obj
            await self.node_queues[node_proto_id].put({'op': 'add', 'uuid': uuid})
            return True, 200, 'Пользователь добавлен'

        raise NodeNotRegisteredError(node_proto_id)

    async def delete_user(
        self,
        node_proto_id: int,
        user_obj: dict | str,
    ):
        """
        Удаляет пользователя из буфера (O(1))

        Args:
            node_proto_id: ID виртуальной ноды
            user_obj: объект пользователя (или строка uuid)

        Raises:
            NodeNotRegisteredError: если нода не зарегистрирована
        """
        from node_client.exceptions import NodeNotRegisteredError

        if node_proto_id not in self.node_metadata or node_proto_id not in self.buffer_storage:
            raise NodeNotRegisteredError(node_proto_id)

        uuid = user_obj['user_uuid'] if isinstance(user_obj, dict) else user_obj

        # Проверяем наличие пользователя
        if uuid not in self.buffer_storage[node_proto_id]:
            filepath = self.node_metadata[node_proto_id]['filepath']
            log_event(
                f'Пользователя с uuid не существует в этом конфиге | uuid: \033[33m{uuid}\033[0m; config_file: \033[32m{filepath}\033[0m',
                level='WARNING',
            )
            return True, 200, 'Пользователя уже не было'

        # Удаляем из кэша и добавляем в очередь
        del self.buffer_storage[node_proto_id][uuid]
        log_event(
            f"Пользователь удалён из буфера | node_proto_id: \033[32m{node_proto_id}\033[0m | uuid: \033[32m{uuid}\033[0m"
        )

        await self.node_queues[node_proto_id].put({'op': 'delete', 'uuid': uuid})
        return True, 200, 'Пользователь удалён'

    async def stop(self):
        """Останавливает все воркеры и безопасно сбрасывает остатки на диск"""
        log_event("Остановка ConfigWriteBuffer...")
        # 1. ОСТАНАВЛИВАЕМ ВОРКЕРЫ ПЕРВЫМ ДЕЛОМ
        # Чтобы они перестали читать очереди и порождать новые pending_writes
        worker_tasks = list(self.worker_tasks.values())
        if worker_tasks:
            for task in worker_tasks:
                task.cancel()
            # Дожидаемся фактической остановки всех воркеров
            await asyncio.gather(*worker_tasks, return_exceptions=True)
            self.worker_tasks.clear()
        # 2. ДОЖИДАЕМСЯ ЗАВЕРШЕНИЯ АКТИВНЫХ ЗАПИСЕЙ
        # Теперь воркеры мертвы, список pending_writes больше не будет пополняться
        all_pending_writes = [task for tasks in self.pending_writes.values() for task in tasks]
        if all_pending_writes:
            log_event(f"Ожидание завершения {len(all_pending_writes)} активных записей I/O...")
            results = await asyncio.gather(*all_pending_writes, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                    log_event(f"Ошибка при завершении pending записи: {repr(result)}", level='ERROR')
            self.pending_writes.clear()
        # 3. СБРАСЫВАЕМ ОСТАТКИ НА ДИСК
        # Очереди теперь заморожены, можно безопасно сбросить остатки
        for node_id in list(self.node_metadata.keys()):
            queue = self.node_queues.get(node_id)
            if queue and not queue.empty():
                log_event(f"Сброс остатков для node_proto_id: \033[33m{node_id}\033[0m")
                await self._write_node_to_disk(node_id)
        log_event("ConfigWriteBuffer полностью остановлен")

    async def bulk_action(
        self,
        node_proto_id: int,
        users: list[dict],
        action: Literal["add", "delete"],
    ):
        """
        Пакетная операция добавления/удаления пользователей

        Args:
            node_proto_id: ID виртуальной ноды
            users: список объектов пользователей
            action: "add" или "delete"

        Raises:
            NodeNotRegisteredError: если нода не зарегистрирована
        """
        from node_client.exceptions import NodeNotRegisteredError

        if node_proto_id not in self.node_metadata:
            raise NodeNotRegisteredError(node_proto_id)

        action_map = {"add": self.add_user, "delete": self.delete_user}

        if len(users) < self.max_batch:
            for u in users:
                await action_map[action](
                    node_proto_id=node_proto_id,
                    user_obj=u,
                )
        else:
            async with self.unlimit_queue(node_proto_id):
                for u in users:
                    await action_map[action](
                        node_proto_id=node_proto_id,
                        user_obj=u,
                    )
        return True, "Операция выполнена"

    async def _load_users_from_config(self, node_id: int):
        """
        Загружает существующих пользователей из конфиг-файла в память

        Создаёт маппинг {uuid: user_obj} для O(1) операций
        """
        metadata = self.node_metadata[node_id]
        try:
            "Читаем конфиг. Если его нет, начинаем с чистого листа"
            # Просто список в памяти будет изначально пуст. При сбросах на диск файл появится сам
            ok, state_config = await self._read_config(f"{metadata['filepath']}.state.json", False)
            state_config = orjson.loads(state_config)

            # Получаем массив clients
            if not ok:
                log_event(
                    f'State Конфиг файл не найден! Начинаем с чистого листа! | node_proto_id: \033[33m{node_id}\033[0m',
                    level='WARNING',
                )

            users_arr = state_config.get('users', [])
            # Создаём маппинг {uuid: user_obj}
            self.buffer_storage[node_id] = {}
            for user_obj in users_arr:
                # Парсим flatten ключ к user_identifier, составляем пару {user_identifier: user_obj}
                user_identifier_value = user_obj['user_uuid']
                self.buffer_storage[node_id][user_identifier_value] = user_obj
            log_event(
                f"Загружено пользователей из конфига | node_proto_id: \033[32m{node_id}\033[0m; count: \033[32m{len(self.buffer_storage[node_id])}\033[0m"
            )
        except Exception as e:
            log_event(
                f"Ошибка загрузки пользователей из State-конфига. Убедитесь, что существует файл \"\033[33m{metadata.get('filepath')}.state.json\033[0m\" | node_proto_id: \033[31m{node_id}\033[0m; error: \033[34m{e}\033[0m",
                level='ERROR',
            )
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
            # Нода удалена из памяти (remove_node) — воркеру больше нечего обслуживать
            if node_id not in self.node_metadata:
                break
            try:
                operations = []
                start_time = time.time()
                # 1. Запоминаем состояние лимита на очередь конкретной ноды перед сборкой батча
                was_limited = self.node_metadata[node_id]['queue_limited']

                # Собираем батч операций
                while len(operations) < self.max_batch:
                    remaining_time = self.timeout - (time.time() - start_time)
                    # Если таймаут истёк
                    if remaining_time <= 0:
                        break
                    try:
                        # Пытаемся забрать операцию с таймаутом
                        op = await asyncio.wait_for(self.node_queues[node_id].get(), timeout=remaining_time)
                        operations.append(op)
                        self.node_queues[node_id].task_done()
                    except TimeoutError:
                        # Таймаут истёк, выходим
                        break

                # Если очередь ограничивается лимитами для этой ноды
                # Если есть операции → пишем на диск (неблокирующе)
                if was_limited and self.node_metadata[node_id]['queue_limited'] and operations:
                    log_event(
                        f"\033[35m[Worker]\033[0m Батч собран | node_proto_id: \033[32m{node_id}\033[0m; opers_len: \033[35m{len(operations)}\033[0m"
                    )
                    # Создаём задачу и отслеживаем её
                    write_task = asyncio.create_task(self._write_node_to_disk(node_id))
                    self.pending_writes[node_id].add(write_task)
                    # Удаляем из pending после завершения
                    write_task.add_done_callback(lambda t: self.pending_writes.get(node_id, set()).discard(t))

            except asyncio.CancelledError:
                break
            except Exception as e:
                log_event(
                    f"\033[35m[Worker]\033[0m Ошибка воркера | node_proto_id: \033[31m{node_id}; error: \033[34m{e}\033[0m",
                    level='CRITICAL',
                )
                # Пауза перед следующей попыткой: без неё повторяющаяся ошибка крутит цикл без единого await
                # и блокирует event loop всего нод-клиента
                await asyncio.sleep(self.timeout)

    async def _write_node_to_disk(self, node_id: int):
        """
        Записывает текущее состояние буфера в конфиг-файл

        НЕ читаем конфиг для получения пользователей - используем буфер!
        """
        metadata = self.node_metadata[node_id]

        try:
            log_event(
                f"\033[34m[Write]\033[0m Запись на диск | node_proto_id: \033[32m{node_id}\033[0m | users: \033[34m{len(self.buffer_storage[node_id])}\033[0m"
            )

            "0. Бэкап State в файл"
            json_bytes = orjson.dumps(
                {'users': list(self.buffer_storage[node_id].values())}, option=orjson.OPT_INDENT_2
            )
            await self._write_config_atomic(f"{metadata['filepath']}.state.json", json_bytes)

            "1. Читаем конфиги. Стейт - для формирирован (только для получения структуры)"
            core_ok, config = await self._read_config(metadata['filepath'], True)
            # Конвертация в json формат
            config = metadata['config2json_script'](config)

            "2. Прогоняем каждый массив операций для конкретно этого ядра"
            for inj in metadata['injectors']:
                clients_array = self._navigate_to_path(config, inj['flatten_array_cursor'])

                "3. Заменяем массив на актуальное состояние буфера. Фишка структуры O(1). Готовые пользовательские объекты для ядра получаем благодаря inj['extractor_script']"
                clients_array.clear()

                transformed_clients = [inj['extractor_script'](su) for su in self.buffer_storage[node_id].values()]
                clients_array.extend(transformed_clients)

            "4. Атомарно записываем конфиг ядра"
            # Конвертация из json в конифг-формат
            config = metadata['json2config_script'](config)
            await self._write_config_atomic(metadata['filepath'], config)

            "5. Перезагружаем ядро (если нужно)"
            if metadata['reload_command']:
                await self._reload_core(metadata['reload_command'])

            log_event(f"\033[34m[Write]\033[0m Успешная запись | node_proto_id: \033[32m{node_id}\033[0m")

        except Exception as e:
            log_event(
                f"\033[34m[Write]\033[0m КРИТИЧЕСКАЯ ошибка записи | node_proto_id: \033[31m{node_id}\033[0m | error: \033[34m{repr(e)}\033[0m",
                level='CRITICAL',
            )

    async def _reload_core(self, reload_command: str):
        """Выполняет команду перезагрузки ядра"""
        try:
            log_event(f'Выполнение команды перезагрузки: "\033[33m{reload_command}\033[0m"')
            process = await asyncio.create_subprocess_shell(
                reload_command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
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
        """
        Временно отключает лимиты очереди для bulk операций для конкретной ноды

        Args:
            node_proto_id: ID ноды для которой отключаем лимиты

        Использование:
            async with buffer.unlimit_queue(node_proto_id):
                # Здесь можно добавлять операции без триггера батчинга
                await buffer.add_user(...)
                await buffer.add_user(...)
            # При выходе автоматически записываем накопленные операции
        """
        # Сохраняем предыдущее состояние конкретной ноды
        previous_state = self.node_metadata[node_proto_id]['queue_limited']
        # Отключаем лимиты для этой ноды
        self.node_metadata[node_proto_id]['queue_limited'] = False
        try:
            yield self
        finally:
            # Восстанавливаем предыдущее состояние
            self.node_metadata[node_proto_id]['queue_limited'] = previous_state
            # Принудительно записываем все накопленные операции на диск
            await self._flush_all_nodes(node_proto_id)

    async def _flush_all_nodes(self, node_proto_id: int):
        """Принудительно записывает все ноды на диск (для bulk операций)"""
        log_event(
            f"\033[35m[Flush]\033[0m Принудительная запись конфиг-файла на инстансе ядра | node_proto_id: \033[33m{node_proto_id}\033[0m"
        )
        await self._write_node_to_disk(node_proto_id)
        self.queue_limited = True

    async def _audit_state(self, node_id: int):
        """
        Сверяет Shadow State (фарш) с реальным конфигом (котлетами).
        mode: 'len_only', 'log_diff', 'strict'
        """
        metadata = self.node_metadata[node_id]
        state_filepath = f"{metadata['filepath']}.state.json"

        try:
            # 1. Читаем фарш (state.json) и конфиг
            state_ok, state_users = await self._read_config(state_filepath, False)
            # В json
            state_users = orjson.loads(state_users)

            core_ok, config = await self._read_config(metadata['filepath'], False)
            # в Json - используем конвертер или orjson.loads по умолчанию
            if metadata['config2json_script'] is None:
                config = orjson.loads(config)
            else:
                config = metadata['config2json_script'](config)

            if not state_ok or not core_ok:
                log_event(
                    f'\033[36m[Audit]\033[0m Предоставлены неправильные конфигурации. Файлы не найдены; node_proto_id: \033[31m{node_id}\033[0m; node_meta: \033[34m{metadata}\033[0m',
                    level='ERROR',
                )
                raise

            state_users = state_users['users']

            # 2. Проверяем каждый инжектор (массив)
            for injector in metadata['injectors']:
                target_array = self._navigate_to_path(config, injector['flatten_array_cursor'])

                "Режим 1: Быстрая проверка длины"
                if len(state_users) != len(target_array):
                    msg = f"Дрифт длины! Ожидалось {len(state_users)}, в ядре {len(target_array)}"
                    log_event(
                        f"\033[36m[Audit]\033[0m Дрифт длины! Ожидалось {len(state_users)}, в ядре {len(target_array)}",
                        level='CRITICAL',
                    )
                    if env.audit_mode == AuditModes.strict:
                        raise ValueError(msg)

                if env.audit_mode == AuditModes.lite:
                    continue

                "Режимы 2 и 3: Глубокая проверка за O(N)"

                # Крутим фарш в ожидаемые котлеты и сериализуем в строки/байты
                expected_cutlets = set(
                    orjson.dumps(
                        injector['extractor_script'](u), option=orjson.OPT_SORT_KEYS
                    )  # .decode() # Если байты не подойдут
                    for u in state_users
                )

                # Сериализуем реальные котлеты из конфига
                actual_cutlets = set(
                    orjson.dumps(c, option=orjson.OPT_SORT_KEYS)  # .decode() # Если байты не подойдут
                    for c in target_array
                )

                # Магия множеств: Слияние - находит расхождения моментально!
                mismatches = expected_cutlets ^ actual_cutlets

                if mismatches:
                    # Кого не хватает, а кто лишний:
                    missing = expected_cutlets - actual_cutlets
                    alien = actual_cutlets - expected_cutlets

                    msg = f'\033[36m[Audit]\033[0m Статистика расхождений | total_mismatches: \033[35m{len(mismatches)}\033[0m; missing: \033[33m{len(missing)}\033[0m; alien: \033[31m{len(alien)}\033[0m'
                    log_event(msg, level='CRITICAL')

                    if env.audit_mode == AuditModes.strict:
                        raise ValueError(msg)

            log_event(f"\033[36m[Audit]\033[0m Аудит пройден успешно | node_proto_id: \033[32m{node_id}\033[0m")
            return True

        except Exception as e:
            log_event(
                f"Ошибка аудита | node_proto_id: \033[32m{node_id}\033[0m; err: \033[31m{repr(e)}\033[0m", level='ERROR'
            )
            if env.audit_mode == AuditModes.strict:
                raise
            return False

    # ========== Утилиты для работы с конфиг-файлами ==========
    @staticmethod
    async def _read_config(filepath: str, raise_exc: bool = False) -> tuple[bool, str]:
        """
        Читает конфиг-файл
        """
        try:
            async with aiofiles.open(filepath, encoding='utf-8') as f:
                content = await f.read()
                return True, content
        except FileNotFoundError:
            log_event(f'Конфиг-файл не найден: "\033[31m{filepath}\033[0m"', level='ERROR')
            if not raise_exc:
                return False, ''

            raise

        except orjson.JSONDecodeError as e:
            log_event(f'Ошибка парсинга JSON в "\033[31m{filepath}\033[0m"; error: \033[34m{e}\033[0m', level='ERROR')
            if not raise_exc:
                return False, ''

            raise

    @staticmethod
    async def _write_config_atomic(filepath: str, bytes_content: bytes):
        """
        Атомарная запись конфига через временный файл

        - file_format: по дефолту всегда JSON(1)
        """
        now = time.monotonic()

        # Используем только имя файла
        filename = os.path.basename(filepath)
        tmp_filepath = TMP_DIR / f"{filename}.{now}.tmp"

        try:
            # 1. Пишем во временный файл
            async with aiofiles.open(tmp_filepath, mode='wb') as f:
                await f.write(bytes_content)
            # 2. Атомарно подменяем старый файл новым. mv в POSIX - один такт процессорного времени, - либо да, либо нет
            os.replace(str(tmp_filepath), filepath)
            log_event(f"Конфиг атомарно обновлён: \033[33m{filepath}\033[0m")
        except Exception as e:
            log_event(
                f'Ошибка атомарной записи "\033[35m{filepath}\033[0m"; error: \033[34m{e}\033[0m', level='CRITICAL'
            )
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
    json_obj: dict,
    flatten_key: str,
    new_last_obj: dict = None,
    replace_last_obj: bool = False,
    delete_obj: bool = False,
):
    """
    Ультимативная функция для парсинга flatten-json ключей
    1. Может просто возращать конечное значение
    2. Удалять последний объект по ключу
    3. Подменять последний объект.
    ВАЖНО: Передача ключа. Предполагается, что файл-контент передан без конечного объекта по ключу
    То есть, изначально содержимое файла было получено с УДАЛЕНИЕМ объекта по этому ключу. Значит, что ключ к пользователям:
    должен быть таким же как при чтении файла

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
        except (ValueError, TypeError, KeyError):
            current = current.get(key, Exception)

        # Ранний выход, если ключ не найден
        if current is Exception:
            return Exception

    return current


@dataclass
class AuditModes:
    lite: str = 'lite'  # Сравнение длины. Лог при расхождении. Нод клиент продолжает работать
    medium: str = (
        'medium'  # Глубокое сравнение каждого пользователя из State файла с пользователем из Конфиг-файла впн-ядра
    )
    strict: str = 'strict'  # Как Medium, но нод клиент прекращает работу и падает с ValueError

    medium_advanced: str = 'medium_advanced'  # Medium. Расхождения отправляются на админку
    strict_advanced: str = 'strict_advanced'  # Strict + Умное уведомление на админку


def get_proto_cores_buffer(request: Request):
    return request.app.state.core_buffer


CoreBuffersDep = Annotated[ConfigWriteBuffer, Depends(get_proto_cores_buffer)]
