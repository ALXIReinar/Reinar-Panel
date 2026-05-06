from asyncpg import Connection


class ProtocolsQueries:
    """Запросы для работы с протоколами VPN"""

    def __init__(self, conn: Connection):
        self.conn = conn

    async def create_protocol(self, name: str) -> int:
        """Создать новый протокол"""
        query = """
        INSERT INTO protocols (name) VALUES ($1)
        ON CONFLICT DO NOTHING
        RETURNING id
        """
        return await self.conn.fetchval(query, name)

    async def get_protocol(self, proto_id: int):
        """Получить протокол по ID"""
        query = "SELECT id, name, created_at FROM protocols WHERE id = $1"
        return await self.conn.fetchrow(query, proto_id)

    async def get_all_protocols(self, offset: int, limit: int):
        """Получить все протоколы"""
        query = "SELECT id, name, created_at FROM protocols LIMIT $1 OFFSET $2"
        return await self.conn.fetch(query, limit, offset)

    async def delete_protocol(self, proto_id: int) -> bool:
        """Удалить протокол"""
        query = "DELETE FROM protocols WHERE id = $1 RETURNING id"
        res = await self.conn.fetchrow(query, proto_id)
        return res
