from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .router import main_router as main_router

__all__ = ["main_router"]


def __getattr__(name: str):  # noqa: V103 — Python вызывает при импорте main_router
    if name == "main_router":
        from .router import main_router

        return main_router
    raise AttributeError(f"{__name__!r} не содержит {name!r}")
