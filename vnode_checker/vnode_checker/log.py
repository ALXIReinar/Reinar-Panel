import logging
from pathlib import Path

logger = logging.getLogger("vnode_checker")


def configure_log(path: Path) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)
    for handler in (logging.StreamHandler(), logging.FileHandler(path, encoding="utf-8")):
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
