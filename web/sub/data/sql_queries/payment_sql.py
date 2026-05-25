from asyncpg import Connection, ForeignKeyViolationError


class PaymentQueries:
    def __init__(self, conn: Connection):
        self.conn = conn


    async def order_subscription(self, user_id: int, sub_plan_id: int):
        query = 'INSERT INTO payed_subs (user_id, sub_plan_id) VALUES ($1, $2) RETURNING id'
        try:
            return await self.conn.fetchval(query, user_id, sub_plan_id)
        except ForeignKeyViolationError:
            return None


    async def activate_subscription(self, order_id: int, ttl_days: int, user_id: int):
        query = '''
        WITH deactivate_old AS (
            UPDATE payed_subs SET is_active = false WHERE user_id = $3
        )
        UPDATE payed_subs SET is_active = true, expire_date = created_at + ($2 || ' days')::interval 
        WHERE id = $1
        '''
        await self.conn.execute(query, order_id, ttl_days, user_id)


    async def get_user_info(self, user_id: int):
        query = 'SELECT uuid, tg_username FROM users WHERE id = $1'
        return await self.conn.fetchrow(query, user_id)


    async def get_expired_subs_grouped_by_node(self):
        """
        Получить истёкшие подписки, сгруппированные по нодам
        
        Возвращает данные в формате, оптимизированном для bulk удаления:
        - Группировка по node_proto_id
        - Все пользователи для каждой ноды в одной строке
        
        Returns:
            list[Record]: [{
                'node_proto_id': int,
                'private_ip': str,
                'api_port': int,
                'users': [{'uuid': str, 'tg_username': str, 'order_id': int, 'sub_node_id': int}]
            }]
        """
        query = '''
        WITH expired_subs AS (
            SELECT 
                u.uuid,
                u.tg_username,
                ps.id as order_id,
                vsp.id as sub_node_id,
                vsp.node_proto_id,
                np.id as node_proto_id,
                n.private_ip,
                n.api_port,
                np.metrics_port,
                pt.proto_python_lib,
                pt.api_delete_user_script,
                pt.reload_core_command,
                np.config_path,
                pt.flatten_json_users_key,
                pt.flatten_user_identifier_key
            FROM payed_subs ps
            JOIN sub_plans sp ON sp.id = ps.sub_plan_id
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = sp.id
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true
            JOIN nodes n ON np.node_id = n.id AND n.is_active = true
            JOIN protocols p ON np.proto_id = p.id
            JOIN proto_templates pt ON p.proto_tmp_id = pt.id
            JOIN users u ON u.id = ps.user_id
            WHERE ps.is_active = true AND ps.expire_date < now()
        )
        SELECT 
            node_proto_id,
            private_ip,
            api_port,
            metrics_port,
            proto_python_lib,
            api_delete_user_script,
            reload_core_command,
            config_path,
            flatten_json_users_key,
            flatten_user_identifier_key,
            json_agg(
                json_build_object(
                    'uuid', uuid,
                    'tg_username', tg_username,
                    'order_id', order_id,
                    'sub_node_id', sub_node_id
                )
            ) as users
        FROM expired_subs
        GROUP BY 
            node_proto_id, private_ip, api_port, metrics_port,
            proto_python_lib, api_delete_user_script, reload_core_command,
            config_path, flatten_json_users_key, flatten_user_identifier_key
        '''
        return await self.conn.fetch(query)