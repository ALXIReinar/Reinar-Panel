from typing import Literal

from asyncpg import Connection

from web.sub.anything import CoreProtoActions, PayStatuses


class SubscriptionQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def get_sub_links(self, b64_string: str):
        query_sub_meta = '''
        SELECT 
            us.sub_plan_id, sp.title, sp.description, (COALESCE(us.traffic_limit_day, us.used_mb_limit, 0)) AS sub_plan_limit, us.user_id, us.uuid AS user_uuid,
            COALESCE(us.traffic_used_day_mb, us.used_mb) AS traffic_used_day_mb, 
            (CASE WHEN us.infinite_expire = true THEN null ELSE us.expire_date END) AS expire_date
        FROM users u
        JOIN user_subs us ON us.user_id = u.id
        JOIN sub_plans sp ON sp.id = us.sub_plan_id
        WHERE us.is_active = true 
          AND u.is_deleted = false
          AND (
                  -- Проверка превышения общего лимита
                  (us.infinite_traffic OR (us.used_mb_limit IS NOT NULL AND us.used_mb < us.used_mb_limit))
                  OR
                  -- Проверка превышения дневного лимита (если он включен)
                  (us.infinite_traffic OR (us.traffic_limit_day IS NOT NULL AND us.traffic_used_day_mb < us.traffic_limit_day))
          )
          AND (us.infinite_expire = true OR us.expire_date > now())
          AND us.b64_id = $1
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
            self, user_uuid: str, user_sub_id: int, operation: CoreProtoActions | int
    ):
        """
        Получить ноды для действия над пользователем в ядре протокола + зафиксировать в outbox
        
        Использует Outbox pattern:
        1. Читает ноды из подписки
        2. Вставляет записи в sub_nodes_outbox
        3. Возвращает полные данные нод для обработки
        """
        query = '''
        WITH vnodes_read AS (
            SELECT vsp.node_proto_id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib,
                   pt.api_add_user_script, pt.api_delete_user_script, pt.reload_core_command, np.config_path, pt.flatten_json_users_key, pt.required_user_data_obj,
                   pt.constant_user_data_obj, pt.flatten_user_identifier_key, pt.add_script_custom_params, pt.delete_script_custom_params
            FROM user_subs us
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = us.sub_plan_id
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true
            JOIN protocols p ON np.proto_id = p.id
            JOIN nodes n ON np.node_id = n.id AND n.is_active = true
            JOIN proto_templates pt ON p.tmp_id = pt.id
            WHERE us.is_active = true AND us.id = $2
        ),
        outbox_insert AS (
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
            SELECT $1, $2, $3, vnodes_read.node_proto_id
            FROM vnodes_read
        )
        SELECT * FROM vnodes_read
        '''
        return await self.conn.fetch(query, user_uuid, user_sub_id, operation)


    async def get_nodes_to_core_proto_action(self, user_sub_id: int):
        query = '''
        SELECT np.id as node_proto_id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib,
           pt.api_add_user_script, pt.api_delete_user_script, pt.reload_core_command, np.config_path, pt.flatten_json_users_key, pt.required_user_data_obj,
           pt.constant_user_data_obj,pt.flatten_user_identifier_key, pt.add_script_custom_params, pt.delete_script_custom_params
        FROM user_subs us
        JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = us.sub_plan_id
        JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true
        JOIN protocols p ON np.proto_id = p.id
        JOIN nodes n ON np.node_id = n.id AND n.is_active = true
        JOIN proto_templates pt ON p.tmp_id = pt.id
        WHERE us.id = $1
        '''
        return await self.conn.fetch(query, user_sub_id)


    async def get_and_lock_expired_subs_grouped_by_node(self):
        """
        Атомарно выключает просроченные подписки, фиксирует их в outbox
        и возвращает сгруппированные по нодам данные для bulk-удаления.
        """
        query = '''
        -- 1. Выключаем просроченные подписки и возвращаем их ID и данные юзеров(Не трогаем бессрочные подписки)
        WITH deactivated_subs AS (
            UPDATE user_subs
            SET is_active = false
            WHERE is_active = true AND expire_date < now() AND infinite_expire = false
            RETURNING id AS user_sub_id, sub_plan_id, uuid, order_id
        ),
        -- 2.Помечаем платёж в общей истории
        change_order_status AS (
            UPDATE pay_orders SET status = $2 
            FROM (SELECT order_id FROM deactivated_subs) AS ds2
            WHERE id = ds2.order_id
        ),
        -- 3. Собираем информацию о нодах для этих подписок
        expired_nodes_info AS (
            SELECT ds.uuid, ds.user_sub_id, vsp.node_proto_id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib,
                   pt.api_bulk_delete_user_script, pt.bulk_delete_script_custom_params, pt.flatten_json_users_key, pt.flatten_user_identifier_key,
                   pt.reload_core_command, np.config_path
            FROM deactivated_subs ds
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = ds.sub_plan_id 
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true 
            JOIN nodes n ON np.node_id = n.id AND n.is_active = true 
            JOIN protocols p ON np.proto_id = p.id 
            JOIN proto_templates pt ON p.tmp_id = pt.id 
        ),
        -- 4. Фиксируем операцию удаления в outbox (двухэтапный ack)
        insert_outbox AS (
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
            SELECT uuid, user_sub_id, $1, node_proto_id
            FROM expired_nodes_info
        )
        -- 5. Группируем пользователей по нодам для пакетной отправки
        SELECT node_proto_id, private_ip, api_port, metrics_port, proto_python_lib, api_bulk_delete_user_script, 
               flatten_json_users_key, flatten_user_identifier_key, reload_core_command, config_path, bulk_delete_script_custom_params,
               COALESCE(
                   json_agg(
                       json_build_object( 
                           'uuid', uuid, 
                           'user_sub_id', user_sub_id,
                           'node_proto_id', node_proto_id
                       )
                   ),
                   '[]'::json
               ) AS users
        FROM expired_nodes_info
        GROUP BY node_proto_id, private_ip, api_port, metrics_port, proto_python_lib, api_bulk_delete_user_script, 
                 flatten_json_users_key, flatten_user_identifier_key, reload_core_command, config_path, bulk_delete_script_custom_params
        '''
        return await self.conn.fetch(query, CoreProtoActions.delete, PayStatuses.expired)


    async def get_sub_nodes_for_bulk_action(self, users: list[dict]):
        user_sub_ids, sub_plan_ids, user_uuids = zip(*tuple(u.values() for u in users))
        # user_sub_ids, sub_plan_ids, user_ids = zip(
        #     *tuple(tuple(u['user_sub_id'], u['sub_plan_id'], u['user_id']) for u in users)
        # )
        query = '''
        WITH users_to_proto_cores AS (
            SELECT user_sub_id, sub_plan_id, uuid 
            FROM UNNEST($1::bigint[], $2::integer[], $3::bigint[]) AS t(user_sub_id, sub_plan_id, uuid)
        ),
        -- 2. Собираем информацию о нодах для этих подписок
        expired_nodes_info AS (
            SELECT upc.uuid, upc.user_sub_id, vsp.id AS sub_node_id,
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
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = upc.sub_plan_id 
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true 
            JOIN nodes n ON np.node_id = n.id AND n.is_active = true 
            JOIN protocols p ON np.proto_id = p.id 
            JOIN proto_templates pt ON p.tmp_id = pt.id 
        )
        -- 3. Группируем пользователей по нодам для пакетной отправки
        SELECT node_proto_id, private_ip, api_port, metrics_port, proto_python_lib, 
               flatten_json_users_key, flatten_user_identifier_key, reload_core_command, config_path, 
               constant_user_data_obj, required_user_data_obj, 
               api_bulk_add_user_script, bulk_add_script_custom_params,
               api_bulk_delete_user_script, bulk_delete_script_custom_params,
               COALESCE(
                   json_agg(
                       json_build_object( 
                           'uuid', uuid, 
                           'user_sub_id', user_sub_id,
                           'node_proto_id', node_proto_id
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
        return await self.conn.fetch(query, user_sub_ids, sub_plan_ids, user_uuids)


    async def success_action_core_proto_user(self, node_proto_ids: list[int], operation: Literal['add', 'delete'], user_uuid: str):
        if not node_proto_ids:
            return

        query = 'DELETE FROM sub_nodes_outbox WHERE user_uuid = $3 AND operation = $2 AND node_proto_id = ANY ($1)'
        await self.conn.execute(query, node_proto_ids, CoreProtoActions.name2id[operation], user_uuid)


    async def success_bulk_action_core_proto_users(self, node_proto_ids: list[int], user_sub_ids: list[int], action: CoreProtoActions | int):
        query = '''
        DELETE FROM sub_nodes_outbox
        WHERE node_proto_id = ANY ($1)
          AND user_sub_id = ANY ($2)
          AND operation = $3
        '''
        await self.conn.execute(query, node_proto_ids, user_sub_ids, action)


    async def update_traffic(self, user_sub_ids: list[str], traffic_add_mbs: list[int]):
        query = """
        -- 1. Атомарно увеличиваем общий и дневной трафик в подписках.
        WITH updated_traffic AS (
            UPDATE user_subs us
            SET used_mb = us.used_mb + t.traffic_add,
                traffic_used_day_mb = us.traffic_used_day_mb + t.traffic_add
            FROM (
                SELECT UNNEST($1::bigint[]) AS user_sub_id, UNNEST($2::bigint[]) AS traffic_add
            ) AS t
            WHERE us.id = t.user_sub_id AND us.is_active = true
            -- Возвращаем актуальные данные для следующего шага(иначе из-за изоляции отобразятся старые данные, нужна передача)
            RETURNING us.id, us.user_id, us.sub_plan_id, us.used_mb, us.used_mb_limit, us.traffic_used_day_mb, us.traffic_limit_day, us.infinite_traffic
        ),
         -- 2. Вычисляем подписки, которые превысили лимиты, и деактивируем их.
         subs_to_disable AS (
            UPDATE user_subs us_to_upd
            SET is_limited = true -- блокируем подписку
            FROM updated_traffic ut
            WHERE us_to_upd.id = ut.id
              AND us_to_upd.is_limited = false
              AND (
                  -- Проверка превышения общего лимита
                  (ut.infinite_traffic AND ut.used_mb_limit IS NOT NULL AND ut.used_mb >= ut.used_mb_limit)
                  OR
                  -- Проверка превышения дневного лимита (если он включен)
                  (ut.infinite_traffic AND ut.traffic_limit_day IS NOT NULL AND ut.traffic_used_day_mb >= ut.traffic_limit_day)
              )
            -- Возвращаем заблокированные подписки для отправки в Outbox
            RETURNING ut.id AS user_sub_id, us_to_upd.uuid, us_to_upd.sub_plan_id
        )
        -- 3. Пишем в outbox на удаление только для заблокированных подписок
        INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
        SELECT std.uuid, std.user_sub_id, $3, vsp.node_proto_id
        FROM subs_to_disable std
        JOIN vnodes_sub_plans vsp ON std.sub_plan_id = vsp.sub_plan_id
        JOIN nodes_protocols np ON vsp.node_proto_id = np.id AND np.user_visible = true
        RETURNING sub_nodes_outbox.id
        """
        return await self.conn.fetch(query, user_sub_ids, traffic_add_mbs, CoreProtoActions.delete)


    async def get_vnodes_by_outbox_events(self, outbox_ids: list[int]):
        query = '''
        -- 1. Собираем информацию о нодах по событиям
        WITH limited_nodes_info AS (
            SELECT us.uuid, us.id AS user_sub_id, sno.node_proto_id, n.private_ip, n.api_port, np.metrics_port,
                   pt.proto_python_lib, pt.api_bulk_delete_user_script, pt.flatten_json_users_key, pt.flatten_user_identifier_key,
                   pt.reload_core_command, np.config_path, pt.bulk_delete_script_custom_params
            FROM (SELECT UNNEST($1::bigint[]) AS outbox_id) AS limited_outbox_events
            JOIN sub_nodes_outbox sno ON sno.id = limited_outbox_events.outbox_id
            JOIN user_subs us ON us.id = sno.user_sub_id
            JOIN nodes_protocols np ON np.id = sno.node_proto_id AND np.user_visible = true 
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
                           'user_sub_id', user_sub_id,
                           'node_proto_id', node_proto_id
                       )
                   ),
                   '[]'::json
               ) AS users
        FROM limited_nodes_info
        GROUP BY node_proto_id, private_ip, api_port, metrics_port, proto_python_lib, api_bulk_delete_user_script, 
                 flatten_json_users_key, flatten_user_identifier_key, reload_core_command, config_path, bulk_delete_script_custom_params
        '''
        return await self.conn.fetch(query, outbox_ids)
