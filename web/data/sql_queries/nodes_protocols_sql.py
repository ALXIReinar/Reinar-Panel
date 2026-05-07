from asyncpg import Connection


class NodesProtocolsQueries:
    """Запросы для работы с виртуальными нодами (протоколы на физических нодах)"""
    
    def __init__(self, conn: Connection):
        self.conn = conn
    
    async def create_node_protocol(self, node_id: int, proto_id: int, config_path: str | None = None) -> int:
        """Добавить протокол на ноду"""
        query = "INSERT INTO nodes_protocols (node_id, proto_id) VALUES ($1, $2) ON CONFLICT DO NOTHING RETURNING id"
        return await self.conn.fetchval(query, node_id, proto_id, config_path)
    
    
    async def get_node_protocol(self, np_id: int):
        """Получить виртуальную ноду по ID"""
        query = """
        SELECT np.node_id, np.proto_id, p.name as proto_name, n.ip as node_ip, n.private_ip as node_private_ip, n.api_port as node_api_port, 
               np.config_path, n.title as node_title, np.created_at, np.updated_at
        FROM nodes_protocols np
        JOIN nodes n ON np.node_id = n.id
        JOIN protocols p ON np.proto_id = p.id
        WHERE np.id = $1
        """
        return await self.conn.fetchrow(query, np_id)
    
    
    async def get_node_protocols(self, node_id: int):
        """Получить все протоколы на физической ноде"""
        query = """
        SELECT np.node_id, np.proto_id, p.name as proto_name, np.config_path, np.created_at, np.updated_at
        FROM nodes_protocols np
        JOIN protocols p ON np.proto_id = p.id
        WHERE np.node_id = $1
        """
        return await self.conn.fetch(query, node_id)
    
    
    async def get_protocol_nodes(self, proto_id: int):
        """Получить все ноды с определённым протоколом"""
        query = """
        SELECT np.id, np.node_id, np.proto_id, n.ip as node_ip, n.private_ip as node_private_ip, np.config_path,
               n.api_port as node_api_port, n.title as node_title, n.is_active as node_is_active, np.created_at, np.updated_at
        FROM nodes_protocols np
        JOIN nodes n ON np.node_id = n.id
        WHERE np.proto_id = $1
        """
        return await self.conn.fetch(query, proto_id)
    
    
    async def get_all_node_protocols(self):
        """Получить все виртуальные ноды"""
        query = """
        SELECT np.node_id, np.proto_id, p.name as proto_name, n.ip as node_ip, n.private_ip as node_private_ip, n.api_port as node_api_port, 
               np.config_path, n.title as node_title, np.created_at, np.updated_at
        FROM nodes_protocols np
        JOIN nodes n ON np.node_id = n.id
        JOIN protocols p ON np.proto_id = p.id
        """
        return await self.conn.fetch(query)
    
    
    async def update_node_protocol(self, np_id: int, config_path: str | None = None):
        """Обновить виртуальную ноду"""
        if config_path is None:
            return
        
        query = "UPDATE nodes_protocols SET config_path = $1, updated_at = NOW() WHERE id = $2"
        await self.conn.execute(query, config_path, np_id)


    async def delete_node_protocol(self, np_id: int):
        """Удалить протокол с ноды"""
        query = "DELETE FROM nodes_protocols WHERE id = $1"
        await self.conn.execute(query, np_id)
