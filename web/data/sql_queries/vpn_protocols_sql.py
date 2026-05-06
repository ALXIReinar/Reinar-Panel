from asyncpg import Connection



class NodesQueries:
    """Запросы для работы с нодами
    
    ВАЖНО: Одна нода = один протокол на одном физическом сервере
    Это позволяет гибко комбинировать протоколы в подписках
    """
    
    def __init__(self, conn: Connection):
        self.conn = conn
    
    async def create_node(self, proto_id: int, ip: str, title: str, 
                         status: str = 'vpn_worker', port: int | None = None) -> int:
        """Создать новую ноду"""
        query = """
            INSERT INTO nodes (proto_id, ip, port, title, status)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
        """
        return await self.conn.fetchval(query, proto_id, ip, port, title, status)
    
    async def get_node(self, node_id: int):
        """Получить ноду по ID с информацией о протоколе"""
        query = """
            SELECT n.id, n.proto_id, n.ip, n.port, n.title, n.status, 
                   n.created_at, n.updated_at,
                   p.name as proto_name
            FROM nodes n
            JOIN protocols p ON n.proto_id = p.id
            WHERE n.id = $1
        """
        return await self.conn.fetchrow(query, node_id)
    
    async def get_all_nodes(self, status: str | None = None, proto_id: int | None = None):
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
            SELECT n.id, n.proto_id, n.ip, n.port, n.title, n.status, 
                   n.created_at, n.updated_at,
                   p.name as proto_name
            FROM nodes n
            JOIN protocols p ON n.proto_id = p.id
            {where_clause}
            ORDER BY n.ip, p.name
        """
        return await self.conn.fetch(query, *params)
    
    async def get_nodes_by_ip(self, ip: str):
        """Получить все ноды на одном физическом сервере (все протоколы на одном IP)"""
        query = """
            SELECT n.id, n.proto_id, n.ip, n.port, n.title, n.status, 
                   n.created_at, n.updated_at,
                   p.name as proto_name
            FROM nodes n
            JOIN protocols p ON n.proto_id = p.id
            WHERE n.ip = $1
            ORDER BY p.name
        """
        return await self.conn.fetch(query, ip)
    
    async def update_node(
            self, node_id: int, proto_id: int | None = None, ip: str | None = None, port: int | None = None, title: str | None = None, status: str | None = None
    ) -> bool:
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
        
        if port is not None:
            updates.append(f"port = ${param_count}")
            params.append(port)
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
            return False
        
        updates.append(f"updated_at = NOW()")
        params.append(node_id)
        
        query = f"""
            UPDATE nodes
            SET {', '.join(updates)}
            WHERE id = ${param_count}
        """
        result = await self.conn.execute(query, *params)
        return result != "UPDATE 0"
    
    async def delete_node(self, node_id: int) -> bool:
        """Удалить ноду"""
        query = "DELETE FROM nodes WHERE id = $1"
        result = await self.conn.execute(query, node_id)
        return result != "DELETE 0"


class ProtoConfigsQueries:
    """Запросы для работы с конфигурациями протоколов на нодах"""
    
    def __init__(self, conn: Connection):
        self.conn = conn
    
    async def create_config(self, node_id: int, path: str) -> int:
        """Создать конфигурацию протокола на ноде"""
        query = """
            INSERT INTO proto_configs (node_id, path)
            VALUES ($1, $2)
            RETURNING id
        """
        return await self.conn.fetchval(query, node_id, path)
    
    async def get_config(self, config_id: int):
        """Получить конфигурацию по ID"""
        query = """
            SELECT pc.id, pc.node_id, pc.path, pc.created_at,
                   n.proto_id, n.title as node_title, n.ip as node_ip, 
                   n.port as node_port, n.status as node_status,
                   p.name as proto_name
            FROM proto_configs pc
            JOIN nodes n ON pc.node_id = n.id
            JOIN protocols p ON n.proto_id = p.id
            WHERE pc.id = $1
        """
        return await self.conn.fetchrow(query, config_id)
    
    async def get_node_config(self, node_id: int):
        """Получить конфигурацию ноды"""
        query = """
            SELECT pc.id, pc.node_id, pc.path, pc.created_at,
                   n.proto_id, n.title as node_title, n.ip as node_ip,
                   n.port as node_port, n.status as node_status,
                   p.name as proto_name
            FROM proto_configs pc
            JOIN nodes n ON pc.node_id = n.id
            JOIN protocols p ON n.proto_id = p.id
            WHERE pc.node_id = $1
        """
        return await self.conn.fetchrow(query, node_id)
    
    async def get_protocol_configs(self, proto_id: int):
        """Получить все конфигурации протокола на всех нодах"""
        query = """
            SELECT pc.id, pc.node_id, pc.path, pc.created_at,
                   n.proto_id, n.title as node_title, n.ip as node_ip,
                   n.port as node_port, n.status as node_status,
                   p.name as proto_name
            FROM proto_configs pc
            JOIN nodes n ON pc.node_id = n.id
            JOIN protocols p ON n.proto_id = p.id
            WHERE n.proto_id = $1
            ORDER BY n.ip
        """
        return await self.conn.fetch(query, proto_id)
    
    async def get_all_configs(self):
        """Получить все конфигурации"""
        query = """
            SELECT pc.id, pc.node_id, pc.path, pc.created_at,
                   n.proto_id, n.title as node_title, n.ip as node_ip,
                   n.port as node_port, n.status as node_status,
                   p.name as proto_name
            FROM proto_configs pc
            JOIN nodes n ON pc.node_id = n.id
            JOIN protocols p ON n.proto_id = p.id
            ORDER BY n.ip, p.name
        """
        return await self.conn.fetch(query)
    
    async def update_config_path(self, config_id: int, path: str) -> bool:
        """Обновить путь к конфигурации"""
        query = """
            UPDATE proto_configs
            SET path = $1
            WHERE id = $2
        """
        result = await self.conn.execute(query, path, config_id)
        return result != "UPDATE 0"
    
    async def delete_config(self, config_id: int) -> bool:
        """Удалить конфигурацию"""
        query = "DELETE FROM proto_configs WHERE id = $1"
        result = await self.conn.execute(query, config_id)
        return result != "DELETE 0"
