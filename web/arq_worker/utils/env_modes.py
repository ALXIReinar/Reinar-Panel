from enum import Enum

class AppMode(str, Enum):
    LOCAL = "local"
    DOCKER = "docker"
    PROD = "prod"
