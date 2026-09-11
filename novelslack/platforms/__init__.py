from .base import (
    PlatformAdapter,
    PlatformPaths,
    TrashCleanResult,
    TrashStatus,
)
from .factory import (
    create_platform_adapter,
    get_platform_adapter,
)

__all__ = [
    "PlatformAdapter",
    "PlatformPaths",
    "TrashCleanResult",
    "TrashStatus",
    "create_platform_adapter",
    "get_platform_adapter",
]
