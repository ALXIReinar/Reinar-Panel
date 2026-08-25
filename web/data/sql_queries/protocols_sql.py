from typing import Literal

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


    async def get_all_protocols(self, order_by: Literal["desc", "asc"], limit: int, proto_id: int | None, tmp_id: int | None):
        sql_params = [limit]
        filters = []
        param_idx = 2

        "Фильтр 'Какие протоколы используют этот шаблон'"
        if tmp_id is not None:
            filters.append(f'p.tmp_id = ${param_idx}')
            sql_params.append(tmp_id)
            param_idx += 1

        "id Based Pagen"
        if proto_id is not None:
            ascend_filter = f'p.id > ${param_idx}'
            if order_by == "desc":
                ascend_filter = f'p.id < ${param_idx}'

            filters.append(ascend_filter)
            sql_params.append(proto_id)

        "Собираем конечный фильтр"
        tmp_filter = ''
        if filters:
            tmp_filter = f'WHERE {" AND ".join(filters)}'

        query = f"""
        SELECT p.id AS proto_id, p.name, p.created_at, p.tmp_id, pt.title AS tmp_name FROM protocols p
        JOIN proto_templates pt ON pt.id = p.tmp_id
        {tmp_filter}
        ORDER BY p.id {order_by}
        LIMIT $1
        """
        return await self.conn.fetch(query, *sql_params)


    async def delete_protocol(self, proto_id: int):
        """Удалить протокол"""
        query = "DELETE FROM protocols WHERE id = $1"

        try:
            await self.conn.execute(query, proto_id)
            return 200, "Протокол удалён"
        except ForeignKeyViolationError:
            return 409, "Протокол не может быть удалён. Некоторые ноды используют его"
