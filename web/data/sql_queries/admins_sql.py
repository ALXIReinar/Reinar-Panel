from asyncpg import Connection

from web.config_dir.config import encryption



class AdminsQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def reg_admin(self, login: str, passw: str):
        query = '''
        INSERT INTO admins (login, passw)
        VALUES($1, $2)
        ON CONFLICT (login) DO NOTHING 
        RETURNING id
        '''
        hashed = encryption.hash(passw)
        res = await self.conn.fetchrow(query, login, hashed)
        return res

    async def select_admin(self, login: str):
        query = 'SELECT id, passw FROM admins WHERE login = $1'
        res = await self.conn.fetchrow(query, login)
        return res

    async def set_new_passw(self, admin_id: int, passw: str):
        query = 'UPDATE admins SET passw = $1 WHERE id = $2'
        await self.conn.execute(query, passw, admin_id)



class AuthQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def make_session(
            self,
            session_id: str,
            admin_id: int,
            iat,
            exp,
            user_agent: str,
            ip: str,
            hashed_rT: str
    ):
        query = '''
        INSERT INTO sessions_admins (session_id, admin_id, iat, exp, refresh_token, user_agent, ip) VALUES($1,$2,$3,$4,$5,$6,$7)
        ON CONFLICT (session_id) DO UPDATE SET iat = $3, exp = $4, refresh_token = $5, user_agent = $6, ip = $7
        '''
        await self.conn.execute(query, session_id, admin_id, iat, exp, hashed_rT, user_agent, ip)


    async def get_actual_rt(self, admin_id: int, session_id: str):
        query = '''
        SELECT refresh_token FROM sessions_admins
        WHERE admin_id = $1 AND session_id = $2 AND "exp" > now()
        '''
        res = await self.conn.fetchrow(query, admin_id, session_id)
        return res


    async def all_seances_user(self, admin_id: int, session_id: str):
        query = 'SELECT user_agent, ip FROM sessions_admins WHERE admin_id = $1 AND session_id = $2'
        res = await self.conn.fetch(query, admin_id, session_id)
        return res

    async def check_exist_session(self, admin_id: int, user_agent: str):
        query = '''
        SELECT session_id FROM sessions_admins WHERE admin_id = $1 AND user_agent = $2
        '''
        res = await self.conn.fetchrow(query, admin_id, user_agent)
        return res

    async def session_termination(self, admin_id: int, session_id: str):
        query = 'DELETE FROM sessions_admins WHERE admin_id = $1 AND session_id = $2'
        await self.conn.execute(query, admin_id, session_id)


    async def slam_refresh_tokens(self):
        query = 'DELETE FROM sessions_admins WHERE exp < now()'
        await self.conn.execute(query)