from pydantic import BaseModel


class UserAddSchema(BaseModel):
    tg_id: int
    tg_username: str
    return_data: bool