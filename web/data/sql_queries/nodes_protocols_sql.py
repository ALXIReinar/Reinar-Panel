from asyncpg import Connection, UniqueViolationError


class NodesProtocolsQueries:
    """Запросы для работы с виртуальными нодами (протоколы на физических нодах)"""
    
    def __init__(self, conn: Connection):
        self.conn = conn
    
    async def create_node_protocol(self, node_id: int, proto_id: int, title: str, sub_node_address: str) -> int:
        """Добавить протокол на ноду"""
        query = """
        INSERT INTO nodes_protocols (node_id, proto_id, title, sub_node_address) VALUES ($1, $2, $3, $4)
        ON CONFLICT DO NOTHING RETURNING id
        """
        return await self.conn.fetchval(query, node_id, proto_id, title, sub_node_address)
    
    
    async def get_node_protocol(self, np_id: int):
        """Получить виртуальную ноду по ID"""
        query = """
        SELECT
            np.node_id, np.proto_id, p.name as proto_name, n.ip as node_ip, n.private_ip as node_private_ip, n.api_port as node_api_port,
            np.sub_node_address, np.proto_port, np.metrics_port, n.is_active, np.user_visible, np.title, np.config_link, 
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
        SELECT 
            np.node_id, np.proto_id, p.name as proto_name, n.ip as node_ip, n.private_ip as node_private_ip, n.api_port as node_api_port,
            np.sub_node_address, np.proto_port, np.metrics_port, n.is_active, np.user_visible, np.title, np.created_at, np.updated_at
        FROM nodes_protocols np
        JOIN protocols p ON np.proto_id = p.id
        JOIN nodes n ON np.node_id = n.id
        WHERE np.node_id = $1
        """
        return await self.conn.fetch(query, node_id)
    
    
    async def get_protocol_nodes(self, proto_id: int):
        """Получить все ноды с определённым протоколом"""
        query = """
        SELECT np.id, np.node_id, np.proto_id, n.ip as node_ip, n.private_ip as node_private_ip, np.config_path,
               n.api_port as node_api_port, np.sub_node_address, n.title as node_title, n.is_active as node_is_active,
               np.created_at, np.updated_at
        FROM nodes_protocols np
        JOIN nodes n ON np.node_id = n.id
        WHERE np.proto_id = $1
        """
        return await self.conn.fetch(query, proto_id)

    
    async def update_node_protocol(
        self,
        np_id: int,
        config_path: str | None = None,
        title: str | None = None,
        metrics_port: int | None = None,
        proto_port: int | None = None,
        sub_node_address: str | None = None,
        user_visible: bool | None = None,
    ) -> tuple[int, str]:
        """
        Универсальное обновление виртуальной ноды
        
        Returns:
            tuple[status_code, message]
            - 200, 'Нода обновлена' - успех
            - 409, 'Конфликт портов...' - нарушение уникального индекса
            - 404, 'Виртуальная нода не найдена' - нода не существует
        """
        updates = []
        params = []
        param_idx = 1

        if config_path is not None:
            updates.append(f"config_path = ${param_idx}")
            params.append(config_path)
            param_idx += 1

        if title is not None:
            updates.append(f"title = ${param_idx}")
            params.append(title)
            param_idx += 1

        if metrics_port is not None:
            updates.append(f"metrics_port = ${param_idx}")
            params.append(metrics_port)
            param_idx += 1

        if proto_port is not None:
            updates.append(f"proto_port = ${param_idx}")
            params.append(proto_port)
            param_idx += 1

        if sub_node_address is not None:
            updates.append(f"sub_node_address = ${param_idx}")
            params.append(proto_port)
            param_idx += 1

        if user_visible is not None:
            updates.append(f"user_visible = ${param_idx}")
            params.append(user_visible)
            param_idx += 1

        if not updates:
            return 200, 'Нет полей для обновления'

        # Всегда обновляем updated_at
        updates.append("updated_at = NOW()")

        query = f"""
        UPDATE nodes_protocols SET {', '.join(updates)}
        WHERE id = ${param_idx}
        RETURNING id
        """
        params.append(np_id)

        try:
            result = await self.conn.fetchval(query, *params)
            if not result:
                return 404, 'Виртуальная нода не найдена'
            
            return 200, 'Виртуальная нода обновлена'

        except UniqueViolationError:
            return 409, 'Конфликт портов: какой-то из (metrics_port, proto_port) уже занят на этом сервере'



    async def delete_node_protocol(self, np_id: int):
        """Удалить протокол с ноды"""
        query = "DELETE FROM nodes_protocols WHERE id = $1"
        await self.conn.execute(query, np_id)


    async def get_all_nodes_for_metrics(self):
        query = '''
        SELECT n.id, n.ip, n.private_ip, n.api_port, np.metrics_port, p.metrics_command, p.metrics_parser_code FROM nodes n
        JOIN nodes_protocols np ON np.node_id = n.id AND np.user_visible = true
        JOIN protocols p ON np.proto_id = p.id
        WHERE n.is_active = true AND np.metrics_port IS NOT NULL
        '''
        return await self.conn.fetch(query)


    async def get_node_for_file_edit(self, node_proto_id: int):
        query = '''
        SELECT n.node_name, np.title, n.ip, n.private_ip, n.api_port, n.is_active, np.user_visible, np.metrics_port, np.proto_port, np.config_path
        FROM nodes_protocols np 
        JOIN nodes n ON np.node_id = n.id
        WHERE np.id = $1
        '''
        return await self.conn.fetchrow(query, node_proto_id)


    async def get_proto_tmp_w_spec_params(self, node_proto_id: int) -> tuple:
        tmp_link_query = '''
        SELECT pt.url_tmp, np.title, np.sub_node_address, n.ip FROM proto_templates pt
        JOIN public.protocols p on pt.id = p.proto_tmp_id
        JOIN nodes_protocols np ON np.node_id = np.id
        JOIN nodes n ON n.id = np.node_id
        WHERE np.id = $1
        '''
        query_spec_params = '''
        SELECT tsp.key, npspv.value FROM nodes_protocoles_spec_params_values npspv
        JOIN template_spec_params tsp ON tsp.id = npspv.spec_key_id
        WHERE npspv.node_proto_id = $1        
        '''
        "Ищем в БД"
        tmp_record = await self.conn.fetchrow(tmp_link_query, node_proto_id)
        spec_params = await self.conn.fetch(query_spec_params, node_proto_id)

        "Обрабатываем в нужный формат"
        config_link_tmp, node_title, node_ip_or_domain = tmp_record['url_tmp'], tmp_record['title'], tmp_record['sub_node_address'] or tmp_record['ip']
        spec_params = {rec['key']: rec['value'] for rec in spec_params}

        return config_link_tmp, spec_params, node_ip_or_domain, node_title


    async def update_config_link(self, node_proto_id: int, sub_ready_link: str):
        query = 'UPDATE nodes_protocols SET updated_at = NOW(), config_link = $2 WHERE id = $1'
        await self.conn.execute(query, node_proto_id, sub_ready_link)


    async def get_core_proto_deps(self, node_proto_id: int):
        query = '''
        SELECT 
        '''