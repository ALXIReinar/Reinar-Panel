from typing import Literal

from asyncpg import Connection

from web.sub.anything import CoreProtoActions, PayStatuses, UserStatuses


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
          AND u.is_deleted = false
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
        JOIN proto_templates pt ON p.tmp_id = pt.id
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
                   pt.constant_user_data_obj, pt.flatten_user_identifier_key, pt.add_script_custom_params, pt.delete_script_custom_params
            FROM payed_subs ps
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = ps.sub_plan_id
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true
            JOIN protocols p ON np.proto_id = p.id
            JOIN nodes n ON np.node_id = n.id AND n.is_active = true
            JOIN proto_templates pt ON p.tmp_id = pt.id
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
           pt.constant_user_data_obj,pt.flatten_user_identifier_key, pt.add_script_custom_params, pt.delete_script_custom_params
        FROM payed_subs ps
        JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = ps.sub_plan_id
        JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true
        JOIN protocols p ON np.proto_id = p.id
        JOIN nodes n ON np.node_id = n.id AND n.is_active = true
        JOIN proto_templates pt ON p.tmp_id = pt.id
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
            RETURNING id AS order_id, sub_plan_id, user_id
        ),
        -- 2. Собираем информацию о нодах для этих подписок
        expired_nodes_info AS (
            SELECT u.uuid, u.tg_username, ds.order_id, vsp.id AS sub_node_id,
                   vsp.node_proto_id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib,
                   pt.api_bulk_delete_user_script, pt.bulk_delete_script_custom_params, pt.flatten_json_users_key, pt.flatten_user_identifier_key,
                   pt.reload_core_command, np.config_path
            FROM deactivated_subs ds
            JOIN users u ON u.id = ds.user_id AND u.is_deleted = false
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = ds.sub_plan_id 
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true 
            JOIN nodes n ON np.node_id = n.id AND n.is_active = true 
            JOIN protocols p ON np.proto_id = p.id 
            JOIN proto_templates pt ON p.tmp_id = pt.id 
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


    async def get_sub_nodes_for_bulk_action(self, users: list[dict]):
        order_ids, sub_plan_ids, user_ids = zip(*tuple(u.values() for u in users))
        # order_ids, sub_plan_ids, user_ids = zip(
        #     *tuple(tuple(u['order_id'], u['sub_plan_id'], u['user_id']) for u in users)
        # )
        query = '''
        WITH users_to_proto_cores AS (
            SELECT order_id, sub_plan_id, user_id 
            FROM UNNEST($1::bigint[], $2::integer[], $3::bigint[]) AS t(order_id, sub_plan_id, user_id)
        ),
        -- 3. Собираем информацию о нодах для этих подписок
        expired_nodes_info AS (
            SELECT u.uuid, u.tg_username, upc.order_id, vsp.id AS sub_node_id,
                   vsp.node_proto_id, n.private_ip, n.api_port, np.metrics_port, 
                   pt.proto_python_lib,
                   pt.flatten_json_users_key, 
                   pt.flatten_user_identifier_key, 
                   pt.reload_core_command,
                   np.config_path, 
                   pt.constant_user_data_obj, 
                   pt.required_user_data_obj,
                   pt.api_bulk_add_user_script,
                   pt.bulk_add_script_custom_params,
                   pt.api_bulk_delete_user_script,
                   pt.bulk_delete_script_custom_params
            FROM users_to_proto_cores upc
            JOIN users u ON u.id = upc.user_id AND u.is_deleted = false
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = upc.sub_plan_id 
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true 
            JOIN nodes n ON np.node_id = n.id AND n.is_active = true 
            JOIN protocols p ON np.proto_id = p.id 
            JOIN proto_templates pt ON p.tmp_id = pt.id 
        )
        -- 5. Группируем пользователей по нодам для пакетной отправки
        SELECT node_proto_id, private_ip, api_port, metrics_port, proto_python_lib, 
               flatten_json_users_key, flatten_user_identifier_key, reload_core_command, config_path, 
               constant_user_data_obj, required_user_data_obj, 
               api_bulk_add_user_script, bulk_add_script_custom_params,
               api_bulk_delete_user_script, bulk_delete_script_custom_params,
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
        GROUP BY node_proto_id, private_ip, api_port, metrics_port, proto_python_lib, 
                 flatten_json_users_key, flatten_user_identifier_key,
                 reload_core_command, config_path, constant_user_data_obj, required_user_data_obj, 
                 api_bulk_add_user_script, bulk_add_script_custom_params,
                 api_bulk_delete_user_script, bulk_delete_script_custom_params
        '''
        return await self.conn.fetch(query, order_ids, sub_plan_ids, user_ids)


    async def success_action_core_proto_user(self, sub_node_ids: list[int], operation: Literal['add', 'delete'], user_uuid: str):
        if not sub_node_ids:
            return

        query = 'DELETE FROM sub_nodes_outbox WHERE user_uuid = $3 AND operation = $2 AND sub_node_id = ANY ($1)'
        await self.conn.execute(query, sub_node_ids, CoreProtoActions.name2id[operation], user_uuid)


    async def success_bulk_core_proto_users(self, sub_node_ids: list[int], order_ids: list[int], action: CoreProtoActions | int):
        query = '''
        DELETE FROM sub_nodes_outbox
        WHERE (sub_node_id, order_id) IN (
            SELECT * FROM UNNEST($1::bigint[], $2::bigint[])
        )
        AND operation = $3
        '''
        await self.conn.execute(query, sub_node_ids, order_ids, action)


    async def update_traffic(self, tg_usernames: list[str], traffic_add_mbs: list[int]):
        query = """
        WITH increase_traffic AS (
            UPDATE users
            SET traffic_used_day_mb = users.traffic_used_day_mb + t.traffic_add, online_status = $3, updated_at = NOW()
            FROM (SELECT UNNEST($1::varchar[]) AS username, UNNEST($2::bigint[]) AS traffic_add) AS t
            WHERE users.tg_username = t.username AND users.is_deleted = false
			RETURNING users.id AS user_id, users.traffic_used_day_mb
        ),
        users_limited AS (
            UPDATE payed_subs SET is_limited = true 
            FROM (
                SELECT it.user_id FROM increase_traffic it
                JOIN payed_subs ps ON ps.user_id = it.user_id AND ps.is_active = true 
                JOIN sub_plans sp ON sp.id = ps.sub_plan_id
                WHERE it.traffic_used_day_mb > sp.traffic_limit_day AND ps.is_limited = false
            ) AS limited_users
            WHERE payed_subs.user_id = limited_users.user_id AND payed_subs.is_active = true
            RETURNING payed_subs.user_id, payed_subs.id, payed_subs.sub_plan_id
        )
        INSERT INTO sub_nodes_outbox (user_uuid, tg_username, order_id, operation, sub_node_id)
        SELECT u.uuid, u.tg_username, ul.id, $4, vsp.id
        FROM users_limited ul
        JOIN vnodes_sub_plans vsp ON ul.sub_plan_id = vsp.sub_plan_id
		JOIN nodes_protocols np ON vsp.node_proto_id = np.id AND np.user_visible = true
        JOIN users u ON ul.user_id = u.id
        RETURNING sub_nodes_outbox.id
        """
        return await self.conn.fetch(query, tg_usernames, traffic_add_mbs, UserStatuses.online, CoreProtoActions.delete)


    async def get_vnodes_by_outbox_events(self, outbox_ids: list[int]):
        query = '''
        -- 1. Собираем информацию о нодах по событиям
        WITH limited_nodes_info AS (
            SELECT u.uuid, u.tg_username, ps.id AS order_id, sno.sub_node_id,
                   vsp.node_proto_id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib,
                   pt.api_bulk_delete_user_script, pt.flatten_json_users_key, pt.flatten_user_identifier_key,
                   pt.reload_core_command, np.config_path, pt.bulk_delete_script_custom_params
            FROM (SELECT UNNEST($1::bigint[]) AS outbox_id) AS limited_outbox_events
            JOIN sub_nodes_outbox sno ON sno.id = limited_outbox_events.outbox_id
            JOIN payed_subs ps ON ps.id = sno.order_id
            JOIN users u ON u.id = ps.user_id
            JOIN vnodes_sub_plans vsp ON vsp.id = sno.sub_node_id 
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true 
            JOIN nodes n ON np.node_id = n.id AND n.is_active = true 
            JOIN protocols p ON np.proto_id = p.id 
            JOIN proto_templates pt ON p.tmp_id = pt.id 
        )
        -- 2. Группируем пользователей по нодам для пакетной отправки
        SELECT node_proto_id, private_ip, api_port, metrics_port, proto_python_lib, api_bulk_delete_user_script, 
               flatten_json_users_key, flatten_user_identifier_key, reload_core_command, config_path, bulk_delete_script_custom_params,
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
        FROM limited_nodes_info
        GROUP BY node_proto_id, private_ip, api_port, metrics_port, proto_python_lib, api_bulk_delete_user_script, 
                 flatten_json_users_key, flatten_user_identifier_key, reload_core_command, config_path, bulk_delete_script_custom_params
        '''
        return await self.conn.fetch(query, outbox_ids)
