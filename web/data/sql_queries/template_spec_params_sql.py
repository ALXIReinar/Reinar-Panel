from asyncpg import Connection, ForeignKeyViolationError

from web.utils.logger_config import log_event


class TemplateSpecParamsQueries:
    def __init__(self, conn: Connection):
        self.conn = conn


    async def get_vnode_spec_params(self, node_proto_id: int):
        query = '''
        SELECT p.tmp_id, tsp.id AS spec_key_id, tsp.key AS key_name, spv.id AS value_id, spv.value FROM nodes_protocoles_spec_params_values spv
        JOIN nodes_protocols np ON spv.node_proto_id = np.id
        JOIN protocols p ON p.id = np.proto_id
        JOIN proto_templates pt ON pt.id = p.tmp_id
        JOIN template_spec_params tsp ON tsp.tmp_id = pt.id AND tsp.id = spv.spec_key_id
        WHERE spv.node_proto_id = $1
        '''
        return await self.conn.fetch(query, node_proto_id)


    async def set_spec_keys(self, tmp_id: int, add_keys: list[dict], upd_keys: list[dict], del_keys: list[int]):
        """
        Управление spec ключами: удаление, обновление, добавление
        
        Args:
            tmp_id: ID шаблона
            add_keys: Список новых ключей для добавления [{"key_id": 0, "key_name": "new"}]
            upd_keys: Список ключей для обновления [{"key_id": 5, "key_name": "updated"}]
            del_keys: Список ID ключей для удаления [1, 2, 3]
        
        Returns:
            tuple[bool, bool, bool]: (del_success, upd_success, add_success)
        """
        del_res, upd_res, add_res = None, None, None

        "1. Удаляем ключи"
        if del_keys:
            try:
                await self.conn.execute("""
                    DELETE FROM template_spec_params 
                    WHERE tmp_id = $1 AND id = ANY($2)
                """, tmp_id, del_keys)
                del_res = True
                log_event(f'Удаление ключей | del_keys_input: {del_keys}; del_res: {del_res}; tmp_id: \033[32m{tmp_id}\033[0m')
            except ForeignKeyViolationError:
                log_event(f'Удаление ключей не удалось, несуществующий tmp_id | del_keys_input: {del_keys}; tmp_id: \033[32m{tmp_id}\033[0m', level='WARNING')
                del_res = False

        "2. Обновляем ключи (UPDATE по key_id)"
        if upd_keys:

            key_ids, key_names = zip(*[upd_pack.values() for upd_pack in upd_keys])

            upd_attempt = await self.conn.fetch("""
                UPDATE template_spec_params 
                SET key = data.new_key
                FROM (
                    SELECT UNNEST($1::integer[]) AS spec_id, UNNEST($2::varchar[]) AS new_key
                ) AS data
                WHERE id = data.spec_id AND tmp_id = $3
                RETURNING id
            """, key_ids, key_names, tmp_id)

            upd_res = len(upd_attempt) == len(upd_keys)
            level = 'INFO' if upd_res else 'WARNING'
            log_event(f'Обновляем ключи | tmp_id: \033[32m{tmp_id}\033[0m; upd_inp: {upd_keys}; upd_out: {upd_attempt}; upd_res: \033[35m{upd_res}\033[0m', level=level)

        "3. Добавляем новые ключи (INSERT)"
        add_attempt = []
        if add_keys:
            try:
                _, key_names = zip(*[add_pack.values() for add_pack in add_keys])

                add_attempt = await self.conn.fetch("""
                    INSERT INTO template_spec_params (tmp_id, key)
                    SELECT $1, UNNEST($2::varchar[])
                    ON CONFLICT (tmp_id, key) DO NOTHING 
                    RETURNING id, key
                """, tmp_id, key_names)
                # Вставка должна быть равна инпуту
                add_res = len(add_attempt) == len(add_keys)
                level = 'INFO' if add_res else 'WARNING'
                log_event(f'Вставка ключей | tmp_id: \033[32m{tmp_id}\033[0m; add_inp: {add_keys}; add_out: {add_attempt}; add_res: \033[33m{add_res}\033[0m', level=level)
            except ForeignKeyViolationError:
                add_res = False

        result = {
            'delete': {
                'success': del_res,
                'message': 'Ключи успешно удалены' if del_res else "Есть значения, ссылающиеся на эти ключи"
            },
            'update': {
                'success': upd_res,
                'message': 'Названия ключей обновлены' if upd_res else 'Убедитесь в уникальности имён всех ключей. Дубликаты остались без изменений'
            },
            'add': {
                'success': add_res,
                'message': 'Новые ключи успешно добавлены' if add_res else 'Убедитесь в уникальности имён всех ключей/Такого шаблона не существует',
                'add_ids': add_attempt,
            }
        }
        return result



    async def set_spec_values(self, node_proto_id: int, new_specs: dict):
        async with self.conn.transaction():
            "1. Удаляем те параметры, которых НЕТ в новом списке (если список не пустой)"
            log_event(f'\033[34mТранзакция\033[0m. Устанавливаем значения по ключам | node_proto_id: \033[33m{node_proto_id}\033[0m; new_specs: \033[36m{new_specs}\033[0m', level='WARNING')
            if new_specs:
                kept_keys = [spec['spec_key_id'] for spec in new_specs]
                await self.conn.execute("""
                    DELETE FROM nodes_protocoles_spec_params_values 
                    WHERE node_proto_id = $1 AND spec_key_id != ALL ($2::bigint[])
                """, node_proto_id, kept_keys)
                log_event(f'Оставили только выбранные specs(остальные удалили) | node_proto_id: \033[33m{node_proto_id}\033[0m')
            else:
                # Если прислали пустой список — сносим всё
                await self.conn.execute("DELETE FROM nodes_protocoles_spec_params_values WHERE node_proto_id = $1", node_proto_id)
                log_event(f'Удалили всё! | node_proto_id: \033[33m{node_proto_id}\033[0m')

            "2. UPSERT, Вставляем новые или обновляем существующие"
            if new_specs:
                query = """
                INSERT INTO nodes_protocoles_spec_params_values (spec_key_id, node_proto_id, value)
                SELECT UNNEST($1::bigint[]), $2, UNNEST($3::varchar[])
                ON CONFLICT (spec_key_id, node_proto_id) DO UPDATE SET value = EXCLUDED.value
                """
                key_ids, values = zip(*[spec_obj.values() for spec_obj in new_specs])

                await self.conn.execute(query, key_ids, node_proto_id, values)
                log_event(f'UPSERT, Установили переданные specs | node_proto_id: \033[33m{node_proto_id}\033[0m; new_specs: \033[34m{new_specs}\033[0m')
