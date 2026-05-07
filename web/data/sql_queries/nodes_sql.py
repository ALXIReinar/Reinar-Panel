from asyncpg import ForeignKeyViolationError, Connection


class NodesQueries:
    """Запросы для работы с нодами

    ВАЖНО: Одна нода = один протокол на одном физическом сервере
    Это позволяет гибко комбинировать протоколы в подписках
    """

    def __init__(self, conn: Connection):
        self.conn = conn

    async def create_node(self, proto_id: int, ip: str, title: str, status: int) -> tuple[int, int]:
        """Создать новую ноду"""
        query = "INSERT INTO nodes (proto_id, ip, title, status) VALUES ($1, $2, $3, $4) RETURNING id"
        try:
            return 200, await self.conn.fetchval(query, proto_id, ip, title, status)
        except ForeignKeyViolationError:
            "Если протокол не найден в родительской таблице"
            return 404, -1

    async def get_node(self, node_id: int):
        """Получить ноду по ID с информацией о протоколе"""
        query = """
        SELECT n.proto_id, n.ip, n.title, n.status, n.created_at, n.updated_at, p.name as proto_name
        FROM nodes n
        JOIN protocols p ON n.proto_id = p.id
        WHERE n.id = $1
        """
        return await self.conn.fetchrow(query, node_id)

    async def get_all_nodes(self, status: int | None = None, proto_id: int | None = None):
        """Получить все ноды, опционально фильтр по статусу и/или протоколу"""
        conditions = []
        params = []
        param_count = 1

        if status:
            conditions.append(f"n.status = ${param_count}")
            params.append(status)
            param_count += 1

        if proto_id:
            conditions.append(f"n.proto_id = ${param_count}")
            params.append(proto_id)
            param_count += 1

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        query = f"""
        SELECT n.id, n.proto_id, n.ip, n.title, n.status, n.created_at, n.updated_at, p.name as proto_name
        FROM nodes n
        JOIN protocols p ON n.proto_id = p.id
        {where_clause}
        """
        return await self.conn.fetch(query, *params)

    async def get_nodes_by_ip(self, ip: str):
        """Получить все ноды на одном физическом сервере (все протоколы на одном IP)"""
        query = """
        SELECT n.id, n.proto_id, n.ip, n.title, n.status, n.created_at, n.updated_at, p.name as proto_name
        FROM nodes n
        JOIN protocols p ON n.proto_id = p.id
        WHERE n.ip = $1 
        """
        return await self.conn.fetch(query, ip)

    async def update_node(
            self, node_id: int, proto_id: int | None = None, ip: str | None = None, title: str | None = None,
            status: str | None = None
    ):
        """Обновить ноду"""
        updates = []
        params = []
        param_count = 1

        if proto_id is not None:
            updates.append(f"proto_id = ${param_count}")
            params.append(proto_id)
            param_count += 1

        if ip is not None:
            updates.append(f"ip = ${param_count}")
            params.append(ip)
            param_count += 1

        if title is not None:
            updates.append(f"title = ${param_count}")
            params.append(title)
            param_count += 1

        if status is not None:
            updates.append(f"status = ${param_count}")
            params.append(status)
            param_count += 1

        if not updates:
            return

        updates.append(f"updated_at = NOW()")
        params.append(node_id)

        query = f"""
        UPDATE nodes SET {', '.join(updates)}
        WHERE id = ${param_count}
        """
        await self.conn.execute(query, *params)

    async def delete_node(self, node_id: int):
        """Удалить ноду"""
        query = "DELETE FROM nodes WHERE id = $1"
        await self.conn.execute(query, node_id)