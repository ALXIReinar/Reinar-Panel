from enum import Enum

class AppMode(str, Enum):
    LOCAL = "local"
    DOCKER = "docker"
    PROD = "prod"


APP_MODE_CONFIG = {
    AppMode.LOCAL: {
        'redis_host': 'redis_host',
        'redis_port': 'redis_port',
    },
    AppMode.DOCKER: {
        'redis_host': 'redis_host',
        'redis_port': 'redis_port',
    },
    AppMode.PROD: {
        'redis_host': 'redis_host',
        'redis_port': 'redis_port',
    },
}