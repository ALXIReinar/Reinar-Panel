import fcntl
import hashlib
import json
import shutil
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .config import CORE_BINARIES
from .db import Row
from .isolation import Stand
from .log import logger
from .manifest import ManifestEntry


@contextmanager
def exclusive_run(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Другой прогон vnode_checker уже выполняется") from None
        yield


def read_results(root: Path) -> list[dict]:
    path = root / "results.jsonl"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def record(root: Path, result: dict) -> None:
    result["finished"] = datetime.now(UTC).isoformat()
    with (root / "results.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")


def versions(stand: Stand, entry: ManifestEntry, template: Row) -> dict:
    root = stand.cfg.scripts_root
    files = {
        "install_script": root / entry.install_script if entry.install_script else None,
        "core_script": root / entry.core / "install.sh",
    }
    evidence = {
        f"{key}_sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path and path.is_file() else None
        for key, path in files.items()
    }
    for key in ("config2json_script", "json2config_script", "url_tmp", "sub_prepare_script"):
        text = template.get(key)
        evidence[f"{key.removesuffix('_script')}_sha256"] = hashlib.sha256(text.encode()).hexdigest() if text else None
    try:
        output = stand.os.run(CORE_BINARIES[entry.core], "version").stdout.splitlines()
    except RuntimeError:
        output = []
    return evidence | {"core_version": output[0] if output else "unknown"}


def snapshot(root: Path, stand: Stand, result: dict, install_dir: Path, rows: list[Row]) -> None:
    node_id = result.get("node_proto_id") if result.get("install_reported_id", True) else None
    directory = root / str(node_id or "_failed") / result["run_id"]
    if not node_id:
        directory /= install_dir.name
    directory.mkdir(parents=True, exist_ok=True)
    result["snapshot"] = str(directory)
    started = datetime.fromisoformat(result["started"])

    def capture(name, read):
        try:
            content = read()
            (directory / name).write_text(content, encoding="utf-8")
        except (OSError, RuntimeError, ValueError) as exc:
            logger.warning("Снимок %s — %s", name, type(exc).__name__)

    unit = result.get("unit")
    if unit:
        capture("journal.txt", lambda: stand.os.journal(unit, started))
    else:
        capture(
            "journal.txt",
            lambda: (
                stand.os.run("journalctl", "--no-pager", "--since", f"@{int(started.timestamp())}", "-n", "200").stdout
            ),
        )
    capture("nodeclient.journal.txt", lambda: stand.os.journal(stand.cfg.node_client_unit, started))
    capture("ss.txt", lambda: stand.os.run("ss", "-lntup").stdout)
    capture("link.txt", lambda: result["s15"].get("link", ""))
    capture(
        "counters.txt",
        lambda: json.dumps(
            {
                "s2": result["s2"],
                "metrics": [item for item in result["s1"].get("checks", []) if item["name"] == "metrics_script"],
            },
            ensure_ascii=False,
            default=str,
        ),
    )
    capture(
        "registrations.json",
        lambda: json.dumps(
            [{key: row.get(key) for key in ("id", "reg_status", "service_name", "config_path")} for row in rows],
            ensure_ascii=False,
            default=str,
        ),
    )
    if config_path := result.get("config_path"):
        path = Path(config_path)
        capture("config" + path.suffix, lambda: path.read_text(encoding="utf-8"))
    for name in ("install.stdout.txt", "install.stderr.txt"):
        source = install_dir / name
        if source.exists():
            shutil.copyfile(source, directory / name)
