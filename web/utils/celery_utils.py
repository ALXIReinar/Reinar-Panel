import json
from datetime import datetime, date
from decimal import Decimal
from uuid import UUID

from asyncpg import Record



def convert(obj):
    if isinstance(obj, Record):
        obj = {key: convert(val) for key, val in obj.items()}
    elif isinstance(obj, dict):
        obj = {key: convert(val) for key, val in obj.items()}
    elif isinstance(obj, list):
        obj = [convert(item) for  item in obj]
    elif isinstance(obj, tuple):
        obj = tuple(convert(item) for  item in obj)
    elif isinstance(obj, set):
        obj = list(convert(item) for item in obj)
    elif isinstance(obj, Decimal):
        obj = str(obj)
    elif isinstance(obj, (datetime, date, UUID)):
        obj = str(obj)
    return obj

def json_dumps(obj):
    return json.dumps(convert(obj), ensure_ascii=False).encode('utf-8')

def json_loads(byte_str):
    return json.loads(byte_str)
