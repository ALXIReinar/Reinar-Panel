from enum import Enum

class AppMode(str, Enum):
    LOCAL = "local"
    PROD = "prod"
    DOCKER = "docker"


APP_MODE_CONFIG = {
    AppMode.LOCAL: {
        "pg_host": "pg_host",
        "pg_port": "pg_port",
        'redis_host': 'redis_host',
        'redis_port': 'redis_port',
    },
    AppMode.DOCKER: {
        "pg_host": "pg_host",
        "pg_port": "pg_port",
        'redis_host': 'redis_host',
        'redis_port': 'redis_port',
    },
    AppMode.PROD: {
        "pg_host": "pg_host",
        "pg_port": "pg_port",
        'redis_host': 'redis_host',
        'redis_port': 'redis_port',
    },
}