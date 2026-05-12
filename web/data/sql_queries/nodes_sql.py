from asyncpg import Connection


class NodesQueries:
    """Запросы для работы с физическими нодами"""
    
    def __init__(self, conn: Connection):
        self.conn = conn
    
    async def create_node(self, ip: str, private_ip: str, api_port: int, node_name: str, title: str, status: int = 1, is_active: bool = True) -> int:
        """Создать физическую ноду"""
        query = """
        INSERT INTO nodes (ip, private_ip, api_port, node_name, title, status, is_active)
        VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id
        """
        return await self.conn.fetchval(query, ip, private_ip, api_port, node_name, title, status, is_active)


    async def get_node(self, node_id: int):
        """Получить ноду по ID"""
        query = """
            SELECT n.id, n.ip, n.private_ip, n.api_port, n.title, n.status, n.is_active,
                   n.created_at, n.updated_at,
                   ns.name as status_name
            FROM nodes n
            LEFT JOIN node_statuses ns ON n.status = ns.id
            WHERE n.id = $1
        """
        return await self.conn.fetchrow(query, node_id)


    async def get_all_nodes(self, status: int | None = None, is_active: bool | None = None):
        """Получить все ноды с опциональными фильтрами"""
        conditions = []
        params = []
        param_count = 1
        
        if status is not None:
            conditions.append(f"n.status = ${param_count}")
            params.append(status)
            param_count += 1
        
        if is_active is not None:
            conditions.append(f"n.is_active = ${param_count}")
            params.append(is_active)
            param_count += 1
        
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        
        query = f"""
        SELECT n.id, n.ip, n.private_ip, n.api_port, n.title, n.status, n.created_at, n.updated_at, n.is_active, ns.name as status_name
        FROM nodes n
        LEFT JOIN node_statuses ns ON n.status = ns.id
        {where_clause}
        """
        return await self.conn.fetch(query, *params)


    async def update_node(
            self, node_id: int, ip: str | None = None, private_ip: str | None = None, api_port: int | None = None,
            title: str | None = None, status: int | None = None, is_active: bool | None = None
    ):
        """Обновить ноду"""
        updates = []
        params = []
        param_count = 1
        
        if ip is not None:
            updates.append(f"ip = ${param_count}")
            params.append(ip)
            param_count += 1
        
        if private_ip is not None:
            updates.append(f"private_ip = ${param_count}")
            params.append(private_ip)
            param_count += 1
        
        if api_port is not None:
            updates.append(f"api_port = ${param_count}")
            params.append(api_port)
            param_count += 1
        
        if title is not None:
            updates.append(f"title = ${param_count}")
            params.append(title)
            param_count += 1
        
        if status is not None:
            updates.append(f"status = ${param_count}")
            params.append(status)
            param_count += 1
        
        if is_active is not None:
            updates.append(f"is_active = ${param_count}")
            params.append(is_active)
            param_count += 1
        
        if not updates:
            return
        
        updates.append(f"updated_at = NOW()")
        params.append(node_id)
        
        query = f"""
        UPDATE nodes
        SET {', '.join(updates)}
        WHERE id = ${param_count}
        """
        await self.conn.execute(query, *params)


    async def delete_node(self, node_id: int):
        """Удалить ноду"""
        query = "DELETE FROM nodes WHERE id = $1"
        await self.conn.execute(query, node_id)
