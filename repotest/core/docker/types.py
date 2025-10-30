from enum import Enum
class CacheMode(str, Enum):
    DOWNLOAD = "download"
    SHARED = "shared"
    LOCAL = "local"
    VOLUME = "volume"