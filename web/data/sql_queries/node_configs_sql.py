from asyncpg import Connection, ForeignKeyViolationError

from bot.logger_config import log_event


class ProtoConfigsQueries:
    """Запросы для работы с конфигурациями протоколов на нодах"""
    
    def __init__(self, conn: Connection):
        self.conn = conn
    
    async def create_config(self, node_id: int, path: str) -> tuple[int, int]:
        """Зарегистрировать конфигурацию протокола на ноде"""
        query = """
        INSERT INTO proto_configs (node_id, proto_id, path) VALUES ($1, $2, $3)
        ON CONFLICT DO NOTHING 
        RETURNING id
        """
        try:
            return 200, await self.conn.fetchval(query, node_id, path)
        except ForeignKeyViolationError as fke:
            log_event(f'Не найден протокол или нода | \033[33m{fke}\033[0m', level='WARNING')
            return 404, -1


    async def get_config(self, config_id: int):
        """Получить конфигурацию по CONFIG_ID

        ЧЕРНОВОЙ ВАРИАНТ. Отдаёт всё. Можно сделать 2 вариации - облегчённая(берёт с основной страницы конфигов нод часть данных), полная

        """
        query = """
        SELECT pc.node_id, n.proto_id, pc.path, p.name as proto_name, n.ip as node_ip, n.title as node_title, n.status as node_status, pc.created_at
        FROM proto_configs pc
        JOIN nodes n ON pc.node_id = n.id
        JOIN protocols p ON n.proto_id = p.id
        WHERE pc.id = $1
        """
        return await self.conn.fetchrow(query, config_id)


    async def get_node_config(self, node_id: int, proto_id: int) -> dict:
        """Получить конфигурацию виртуальной ноды"""
        query = """
        SELECT pc.node_id, n.proto_id, pc.path, p.name as proto_name, n.ip as node_ip, n.title as node_title, n.status as node_status, pc.created_at
        FROM proto_configs pc
        JOIN nodes n ON pc.node_id = n.id
        JOIN protocols p ON n.proto_id = p.id
        WHERE pc.node_id = $1 AND pc.proto_id = $2 
        """
        return await self.conn.fetchrow(query, node_id, proto_id)


    async def get_protocol_configs(self, proto_id: int):
        """Получить все конфигурации протокола на всех нодах"""
        query = """
        SELECT pc.id, pc.node_id, n.proto_id, p.name as proto_name, n.ip as node_ip, n.title as node_title, n.status as node_status, pc.created_at
        FROM proto_configs pc
        JOIN nodes n ON pc.node_id = n.id
        JOIN protocols p ON n.proto_id = p.id
        WHERE n.proto_id = $1
        """
        return await self.conn.fetch(query, proto_id)


    async def get_all_configs(self):
        """Получить все конфигурации"""
        query = """
        SELECT pc.id, pc.node_id, n.proto_id, p.name as proto_name, n.ip as node_ip, n.title as node_title, n.status as node_status, pc.created_at
        FROM proto_configs pc
        JOIN nodes n ON pc.node_id = n.id
        JOIN protocols p ON n.proto_id = p.id
        """
        return await self.conn.fetch(query)


    async def update_config_path(self, config_id: int, path: str):
        """Обновить путь к конфигурации"""
        query = "UPDATE proto_configs SET path = $1 WHERE id = $2"
        await self.conn.execute(query, path, config_id)


    async def delete_config(self, config_id: int):
        """Удалить конфигурацию"""
        query = "DELETE FROM proto_configs WHERE id = $1"
        await self.conn.execute(query, config_id)
