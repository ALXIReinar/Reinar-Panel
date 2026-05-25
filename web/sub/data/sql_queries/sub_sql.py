from typing import Literal

from asyncpg import Connection

from web.sub.anything import CoreProtoActions


class SubscriptionQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def get_sub_links(self, b64_string: str):
        query_sub_meta = '''
        SELECT 
            ps.sub_plan_id, sp.title, sp.traffic_limit_day AS sub_plan_limit, u.id AS user_id, u.uuid AS user_uuid,
            u.traffic_used_day_mb, ps.expire_date
        FROM users u
        JOIN payed_subs ps ON ps.user_id = u.id
        JOIN sub_plans sp ON sp.id = ps.sub_plan_id
        WHERE u.b64_id = $1 AND ps.expire_date > now() AND ps.is_active = true 
        '''
        sub_meta = await self.conn.fetchrow(query_sub_meta, b64_string)
        if not sub_meta:
            return None, []

        query_locations = '''
        SELECT pt.sub_prepare_script, pt.sub_required_libs as required_libs, np.config_link, np.id AS node_proto_id, vsp.id AS sub_node_id
        FROM sub_plans sp
        JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = sp.id
        JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true
        JOIN protocols p ON p.id = np.proto_id
        JOIN proto_templates pt ON p.proto_tmp_id = pt.id
        WHERE sp.id = $1
        '''
        locations = await self.conn.fetch(query_locations, sub_meta['sub_plan_id'])
        return sub_meta, locations


    async def get_core_proto_deps_by_user_id(
            self, user_id: int, user_uuid: str, tg_username: str, order_id: int, operation: Literal['add', 'delete']
    ):
        """
        Получить ноды для действия над пользователем в ядре протокола + зафиксировать в outbox
        
        Использует Outbox pattern:
        1. Читает ноды из подписки
        2. Вставляет записи в sub_nodes_outbox со статусом 'is_retried = false'
        3. Возвращает полные данные нод для обработки
        """
        query = '''
        WITH vnodes_read AS (
            SELECT np.id as node_proto_id, vsp.id AS sub_node_id,n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib,
                   pt.api_add_user_script, pt.api_delete_user_script, pt.reload_core_command, np.config_path, pt.flatten_json_users_key, pt.required_user_data_obj,
                   pt.constant_user_data_obj,pt.flatten_user_identifier_key
            FROM payed_subs ps
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = ps.sub_plan_id
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true
            JOIN protocols p ON np.proto_id = p.id
            JOIN nodes n ON np.node_id = n.id AND n.is_active = true
            JOIN proto_templates pt ON p.proto_tmp_id = pt.id
            WHERE ps.is_active = true AND ps.user_id = $1
        ),
        outbox_insert AS (
            INSERT INTO sub_nodes_outbox (user_uuid, tg_username, order_id, operation, sub_node_id)
            SELECT $2, $3, $4, $5, vnodes_read.sub_node_id
            FROM vnodes_read
        )
        SELECT * FROM vnodes_read
        '''
        return await self.conn.fetch(query, user_id, user_uuid, tg_username, order_id, CoreProtoActions.name2id[operation])


    async def users_on_core_proto_action(
            self, user_uuids: list[int], tg_usernames: list[str], order_ids: list[int], sub_node_ids: list[int], operation: Literal['add', 'delete']
    ):
        query = '''
        WITH vnodes_read AS (
            SELECT np.id as node_proto_id, vsp.id AS sub_node_id,n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib,
                   pt.api_add_user_script, pt.api_delete_user_script, pt.reload_core_command, np.config_path, pt.flatten_json_users_key, pt.required_user_data_obj,
                   pt.constant_user_data_obj,pt.flatten_user_identifier_key
            FROM payed_subs ps
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = ps.sub_plan_id
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true
            JOIN protocols p ON np.proto_id = p.id
            JOIN nodes n ON np.node_id = n.id AND n.is_active = true
            JOIN proto_templates pt ON p.proto_tmp_id = pt.id
            WHERE ps.is_active = true AND ps.user_id = $1
        ),
        outbox_insert AS (
            INSERT INTO sub_nodes_outbox (user_uuid, tg_username, order_id, sub_node_id, operation)
            SELECT u_uuid, tg_uname, ord_id, vnode_id, $5
            FROM UNNEST($1::text[], $2::text[], $3::bigint[], $4::bigint[]) AS t(u_uuid, tg_uname, ord_id, vnode_id)
        )
        SELECT * FROM vnodes_read
        '''
        return await self.conn.fetch(query, user_uuids, tg_usernames, order_ids, sub_node_ids, CoreProtoActions.name2id[operation])


    async def success_action_core_proto_user(self, sub_node_ids: list[int]):
        if not sub_node_ids:
            return []

        query = 'DELETE FROM sub_nodes_outbox WHERE sub_node_id = ANY ($1)'
        return await self.conn.execute(query, sub_node_ids)

