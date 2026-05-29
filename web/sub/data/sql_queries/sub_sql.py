from typing import Literal

from asyncpg import Connection

from web.sub.anything import CoreProtoActions, PayStatuses


class SubscriptionQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def get_sub_links(self, b64_string: str):
        query_sub_meta = '''
        SELECT 
            ps.sub_plan_id, sp.title, sp.description, sp.traffic_limit_day AS sub_plan_limit, u.id AS user_id, u.uuid AS user_uuid,
            u.traffic_used_day_mb, ps.expire_date
        FROM users u
        JOIN payed_subs ps ON ps.user_id = u.id
        JOIN sub_plans sp ON sp.id = ps.sub_plan_id
        WHERE ps.is_active = true 
          AND u.traffic_used_day_mb < sp.traffic_limit_day
          AND ps.expire_date > now() 
          AND u.b64_id = $1
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


    async def get_nodes_to_core_proto_action(self, order_id: int):
        query = '''
        SELECT np.id as node_proto_id, vsp.id AS sub_node_id,n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib,
           pt.api_add_user_script, pt.api_delete_user_script, pt.reload_core_command, np.config_path, pt.flatten_json_users_key, pt.required_user_data_obj,
           pt.constant_user_data_obj,pt.flatten_user_identifier_key
        FROM payed_subs ps
        JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = ps.sub_plan_id
        JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true
        JOIN protocols p ON np.proto_id = p.id
        JOIN nodes n ON np.node_id = n.id AND n.is_active = true
        JOIN proto_templates pt ON p.proto_tmp_id = pt.id
        WHERE ps.id = $1
        '''
        return await self.conn.fetch(query, order_id)


    async def get_and_lock_expired_subs_grouped_by_node(self):
        """
        Атомарно выключает просроченные подписки, фиксирует их в outbox
        и возвращает сгруппированные по нодам данные для bulk-удаления.
        """
        query = '''
        -- 1. Выключаем просроченные подписки и возвращаем их ID и данные юзеров
        WITH deactivated_subs AS (
            UPDATE payed_subs
            SET is_active = false, status = $2
            WHERE is_active = true AND expire_date < now()
            RETURNING id AS order_id, user_id, sub_plan_id
        ),
        -- 2. Собираем информацию о нодах для этих подписок
        expired_nodes_info AS (
            SELECT u.uuid, u.tg_username, ds.order_id, vsp.id AS sub_node_id,
                   vsp.node_proto_id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib,
                   pt.api_bulk_delete_user_script, pt.flatten_json_users_key, pt.flatten_user_identifier_key,
                   pt.reload_core_command, np.config_path
            FROM deactivated_subs ds
            JOIN users u ON u.id = ds.user_id
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = ds.sub_plan_id 
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true 
            JOIN nodes n ON np.node_id = n.id AND n.is_active = true 
            JOIN protocols p ON np.proto_id = p.id 
            JOIN proto_templates pt ON p.proto_tmp_id = pt.id 
        ),
        -- 3. Фиксируем операцию удаления в outbox (двухэтапный ack)
        insert_outbox AS (
            INSERT INTO sub_nodes_outbox (user_uuid, tg_username, order_id, operation, sub_node_id)
            SELECT uuid, tg_username, order_id, $1, sub_node_id
            FROM expired_nodes_info
        )
        -- 4. Группируем пользователей по нодам для пакетной отправки
        SELECT node_proto_id, private_ip, api_port, metrics_port, proto_python_lib, api_bulk_delete_user_script, 
               flatten_json_users_key, flatten_user_identifier_key, reload_core_command, config_path,
               COALESCE(
                   json_agg(
                       json_build_object( 
                           'uuid', uuid, 
                           'tg_username', tg_username,
                           'order_id', order_id,
                           'sub_node_id', sub_node_id
                       )
                   ),
                   '[]'::json
               ) AS users
        FROM expired_nodes_info
        GROUP BY node_proto_id, private_ip, api_port, metrics_port, proto_python_lib, api_bulk_delete_user_script, 
                 flatten_json_users_key, flatten_user_identifier_key, reload_core_command, config_path
        '''
        return await self.conn.fetch(query, CoreProtoActions.delete, PayStatuses.expired)


    async def success_action_core_proto_user(self, sub_node_ids: list[int], operation: Literal['add', 'delete'], user_uuid: str):
        if not sub_node_ids:
            return

        query = 'DELETE FROM sub_nodes_outbox WHERE user_uuid = $3 AND operation = $2 AND sub_node_id = ANY ($1)'
        await self.conn.execute(query, sub_node_ids, CoreProtoActions.name2id[operation], user_uuid)


    async def success_bulk_delete_core_proto_users(self, sub_node_ids: list[int], order_ids: list[int]):
        query = '''
        DELETE FROM sub_nodes_outbox
        WHERE (sub_node_id, order_id) IN (
            SELECT * FROM UNNEST($1::bigint[], $2::bigint[])
        )
        AND operation = $3
        '''
        await self.conn.execute(query, sub_node_ids, order_ids, CoreProtoActions.delete)