from asyncpg import Connection, ForeignKeyViolationError


class ProtocolsQueries:
    """Запросы для работы с протоколами VPN"""

    def __init__(self, conn: Connection):
        self.conn = conn

    async def create_protocol(self, name: str, tmp_id: int):
        """Создать новый протокол"""
        query = """
        INSERT INTO protocols (name, tmp_id) VALUES ($1, $2)
        ON CONFLICT DO NOTHING
        RETURNING id
        """
        try:
            return 200, 'Протокол создан', await self.conn.fetchval(query, name, tmp_id)
        except ForeignKeyViolationError:
            return 404, 'Выбранный шаблон не найден', None


    async def get_protocol(self, proto_id: int):
        """Получить протокол по ID"""
        query_proto = """
        SELECT p.id AS proto_id, p.name, p.created_at, p.tmp_id, pt.url_tmp, pt.sub_prepare_script FROM protocols p
        JOIN proto_templates pt ON pt.id = p.tmp_id
        WHERE p.id = $1
        """
        proto_info = await self.conn.fetchrow(query_proto, proto_id)
        if not proto_info:
            return 404, 'Протокол не найден', None

        return 200, '', proto_info


    async def get_all_protocols(self, offset: int, limit: int):
        """Получить все протоколы"""
        query = """
        SELECT p.id AS proto_id, p.name, p.created_at, p.tmp_id, pt.title AS tmp_name FROM protocols p
        JOIN proto_templates pt ON pt.id = p.tmp_id
        LIMIT $1 OFFSET $2
        """
        return await self.conn.fetch(query, limit, offset)


    async def delete_protocol(self, proto_id: int):
        """Удалить протокол"""
        query = "DELETE FROM protocols WHERE id = $1 RETURNING id"

        try:
            return 200, "Протокол удалён", await self.conn.fetchrow(query, proto_id)
        except ForeignKeyViolationError:
            return 409, "Протокол не может быть удалён. Некоторые ноды используют его"
