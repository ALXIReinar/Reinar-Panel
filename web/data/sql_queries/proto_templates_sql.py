from asyncpg import Connection, UniqueViolationError
from asyncpg.exceptions import ForeignKeyViolationError

from web.schemas.templates_schema import UserInjector


class ProtoTemplatesQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def get_all(self, last_id: int | None, sort_by: str, limit: int):
        """Получить список всех шаблонов с пагинацией и фильтрацией по proto_id"""
        
        # Формируем WHERE условия
        where_conditions = []
        params = [limit]
        param_idx = 2
        
        # Cursor condition (для пагинации)
        if last_id is not None:
            if sort_by == 'asc':
                where_conditions.append(f"pt.id > ${param_idx}")
            else:
                where_conditions.append(f"pt.id < ${param_idx}")
            params.append(last_id)
            param_idx += 1
        
        # Фильтр по proto_id (если указан)
        # proto_join = ''
        # if proto_id is not None:
        #     proto_join = 'JOIN protocols p ON p.tmp_id = pt.id'
        #     where_conditions.append(f"p.id = ${param_idx}")
        #     params.append(proto_id)
        #     param_idx += 1

        # Собираем WHERE clause
        where_clause = ''
        if where_conditions:
            where_clause = 'WHERE ' + ' AND '.join(where_conditions)
        
        query = f"""
        SELECT pt.id, pt.title, pt.url_tmp, pt.status, pt.is_accepted, pt.proto_python_lib
        FROM proto_templates pt
        {where_clause}
        ORDER BY pt.id {sort_by}
        LIMIT $1
        """
        
        tmps = await self.conn.fetch(query, *params)
        return tmps



    async def get_by_id(self, tmp_id: int):
        """Получить шаблон по ID с привязанными"""
        template_query = """
        WITH user_injectors AS (
            SELECT tmp_id, 
                    json_agg(
                        json_build_object(
                            'extractor_script', extractor_script,
                            'flatten_array_cursor', flatten_array_cursor,
                            'libs', libs
                        )
                    ) AS user_injectors
            FROM templates_users_extractors
            WHERE tmp_id = $1
            GROUP BY tmp_id
        
        )
        SELECT pt.id, pt.title, pt.url_tmp, pt.status, pt.is_accepted, pt.reload_core_command, pt.required_user_data_obj, pt.constant_user_data_obj,
               pt.proto_python_lib, pt.sub_prepare_script, pt.sub_required_libs, pt.api_bulk_delete_user_script, pt.metrics_parser_code, pt.metrics_command,
               pt.bulk_delete_script_custom_params, pt.api_metrics_script, pt.api_bulk_add_user_script, pt.bulk_add_script_custom_params, pt.description,
               pt.json2config_script, pt.config2json_script, pt.conf_converter_libs, pt.metrics_parser_libs,
               COALESCE(ui.user_injectors, '[]'::json) AS user_injectors
        FROM proto_templates pt
        LEFT JOIN user_injectors ui ON ui.tmp_id = pt.id
        WHERE pt.id = $1
        """

        template = await self.conn.fetchrow(template_query, tmp_id)
        if not template:
            return None

        return {'template': template}


    async def create(self, title: str) -> tuple[int, str, int | None]:
        """
        Создать новый шаблон
        
        Returns:
            tuple[status_code, message, template_id]
            - 201, 'Шаблон создан', template_id - успех
            - 409, 'Шаблон с таким названием уже существует', None - конфликт
        """
        query = "INSERT INTO proto_templates (title) VALUES ($1) RETURNING id"

        try:
            tmp_id = await self.conn.fetchval(query, title)
            return 201, 'Шаблон создан', tmp_id

        except UniqueViolationError:
            return 409, 'Шаблон с таким названием уже существует', None


    async def update(
        self,
        tmp_id: int,
        title: str | None,
        url_tmp: str | None,
        reload_core_command: str | None,
        required_user_data_obj: dict | None,
        constant_user_data_obj: dict | None,
        proto_python_lib: str | None,
        sub_prepare_script: str | None,
        sub_required_libs: str | None,
        api_bulk_delete_user_script: str | None,
        api_bulk_add_user_script: str | None,
        metrics_parser_code: str | None,
        metrics_command: str | None,
        bulk_delete_script_custom_params: dict | None,
        bulk_add_script_custom_params: dict | None,
        api_metrics_script: str | None | int,
        json2config_script: str | None | int,
        config2json_script: str | None | int,
        conf_converter_libs: str | None | int,
    ) -> tuple[int, str]:
        """
        Обновить шаблон (универсальный метод для всех полей)
        
        Returns:
            tuple[status_code, message]
            - 200, 'Шаблон обновлён' - успех
            - 404, 'Шаблон не найден' - не существует
        """
        updates = []
        params = []
        param_idx = 1

        if title is not None:
            updates.append(f"title = ${param_idx}")
            params.append(title)
            param_idx += 1

        if url_tmp is not None:
            updates.append(f"url_tmp = ${param_idx}")
            params.append(url_tmp)
            param_idx += 1

        if reload_core_command is not None and reload_core_command != 0:
            updates.append(f"reload_core_command = ${param_idx}")
            params.append(reload_core_command)
            param_idx += 1

        if required_user_data_obj is not None:
            updates.append(f"required_user_data_obj = ${param_idx}")
            params.append(required_user_data_obj)
            param_idx += 1

        if constant_user_data_obj is not None:
            updates.append(f"constant_user_data_obj = ${param_idx}")
            params.append(constant_user_data_obj)
            param_idx += 1

        if proto_python_lib is not None and proto_python_lib != 0:
            updates.append(f"proto_python_lib = ${param_idx}")
            params.append(proto_python_lib)
            param_idx += 1

        if sub_prepare_script is not None and sub_prepare_script != 0:
            updates.append(f"sub_prepare_script = ${param_idx}")
            params.append(sub_prepare_script)
            param_idx += 1

        if sub_required_libs is not None and sub_required_libs != 0:
            updates.append(f"sub_required_libs = ${param_idx}")
            params.append(sub_required_libs)
            param_idx += 1

        if api_bulk_delete_user_script is not None and api_bulk_delete_user_script != 0:
            updates.append(f"api_bulk_delete_user_script = ${param_idx}")
            params.append(api_bulk_delete_user_script)
            param_idx += 1

        if api_bulk_add_user_script is not None and api_bulk_add_user_script != 0:
            updates.append(f"api_bulk_add_user_script = ${param_idx}")
            params.append(api_bulk_add_user_script)
            param_idx += 1

        if metrics_parser_code is not None:
            updates.append(f"metrics_parser_code = ${param_idx}")
            params.append(metrics_parser_code)
            param_idx += 1

        if metrics_command is not None:
            updates.append(f"metrics_command = ${param_idx}")
            params.append(metrics_command)
            param_idx += 1

        if bulk_delete_script_custom_params is not None:
            updates.append(f"bulk_delete_script_custom_params = ${param_idx}")
            params.append(bulk_delete_script_custom_params)
            param_idx += 1

        if bulk_add_script_custom_params is not None:
            updates.append(f"bulk_add_script_custom_params = ${param_idx}")
            params.append(bulk_add_script_custom_params)
            param_idx += 1

        if api_metrics_script is not None and api_metrics_script != 0:
            updates.append(f"api_metrics_script = ${param_idx}")
            params.append(api_metrics_script)
            param_idx += 1

        if json2config_script is not None and json2config_script != 0:
            updates.append(f"json2config_script = ${param_idx}")
            params.append(json2config_script)
            param_idx += 1

        if config2json_script is not None and config2json_script != 0:
            updates.append(f"config2json_script = ${param_idx}")
            params.append(config2json_script)
            param_idx += 1

        if conf_converter_libs is not None and conf_converter_libs != 0:
            updates.append(f"conf_converter_libs = ${param_idx}")
            params.append(conf_converter_libs)
            param_idx += 1

        if not updates:
            return 200, 'Нет полей для обновления'

        query = f"""
        UPDATE proto_templates SET {', '.join(updates)}
        WHERE id = ${param_idx}
        RETURNING id
        """
        params.append(tmp_id)

        result = await self.conn.fetchrow(query, *params)
        if not result:
            return 404, 'Шаблон не найден'

        return 200, 'Шаблон обновлён'


    async def delete(self, tmp_id: int) -> tuple[int, str]:
        """
        Удалить шаблон
        
        Returns:
            tuple[status_code, message]
            - 200, 'Шаблон удалён' - успех
            - 404, 'Шаблон не найден' - не существует
            - 409, 'Невозможно удалить: шаблон используется' - RESTRICT
        """
        query = "DELETE FROM proto_templates WHERE id = $1 RETURNING id"

        try:
            result = await self.conn.fetchval(query, tmp_id)
            if not result:
                return 404, 'Шаблон не найден'

            return 200, 'Шаблон удалён'

        except ForeignKeyViolationError:
            "RESTRICT на удаление шаблона, если есть ссылающиеся записи"
            return 409, 'Невозможно удалить: шаблон используется виртуальными нодами'


    async def edit_user_injectors(self, tmp_id: int, injs_state: list[UserInjector]):
        """
        Обновить user_injectors шаблона (удалить старые и вставить новые).
        
        Returns:
            True - успех
            False - шаблон не существует (ForeignKeyViolationError)
        """
        # Сначала удаляем все старые инжекторы
        delete_query = 'DELETE FROM templates_users_extractors WHERE tmp_id = $1'
        await self.conn.execute(delete_query, tmp_id)
        
        # Если список пустой - просто возвращаем успех (все инжекторы удалены)
        if not injs_state:
            # Проверяем что шаблон существует
            template_exists = await self.conn.fetchval(
                'SELECT EXISTS(SELECT 1 FROM proto_templates WHERE id = $1)',
                tmp_id
            )
            return template_exists
        
        # Вставляем новые инжекторы
        insert_query = '''
        INSERT INTO templates_users_extractors (tmp_id, flatten_array_cursor, extractor_script, libs)
        SELECT $1, t.flatten_ac, t.extractor_script, t.libs
        FROM UNNEST($2::varchar[], $3::text[], $4::varchar[]) AS t(flatten_ac, extractor_script, libs)
        '''
        try:
            arr_cursors, extractors, libs = zip(*[(inj.flatten_array_cursor, inj.extractor_script, inj.libs) for inj in injs_state])
            await self.conn.execute(insert_query, tmp_id, arr_cursors, extractors, libs)
            return True
        except ForeignKeyViolationError:
            return False
