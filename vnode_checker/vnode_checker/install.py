import json
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .manual import InstallStep, render_session


@dataclass(frozen=True)
class Installation:
    returncode: int | None
    node_id: int | None
    unit: str | None
    cert_paths: dict[str, str]


def install(steps: list[InstallStep], directory: Path, timeout: int) -> Installation:
    directory.mkdir(parents=True, exist_ok=True)
    stdout = directory / "install.stdout.txt"
    stderr = directory / "install.stderr.txt"
    environment = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "LC_ALL") if key in os.environ}
    with stdout.open("wb") as out, stderr.open("wb") as err:
        with subprocess.Popen(
            ["bash", "-c", render_session(steps)], stdout=out, stderr=err, env=environment, start_new_session=True
        ) as process:
            try:
                returncode = process.wait(timeout)
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                if isinstance(exc, KeyboardInterrupt):
                    raise
                returncode = None

    lines = stdout.read_text(errors="replace").splitlines()
    node_id, unit = None, None
    # jq по умолчанию записывает объект результата на нескольких строках.
    for index in range(len(lines) - 1, -1, -1):
        if not lines[index].lstrip().startswith("{"):
            continue
        try:
            data = json.loads("\n".join(lines[index:]))
        except ValueError:
            continue
        raw_id = data.get("node_proto_id")
        service_name = data.get("service_name")
        if type(raw_id) is int or isinstance(raw_id, str) and raw_id.isascii() and raw_id.isdecimal():
            try:
                parsed_id = int(raw_id)
            except ValueError:
                break
            if parsed_id > 0 and isinstance(service_name, str) and service_name:
                node_id, unit = parsed_id, service_name
        break

    cert_paths = {}
    for line in stderr.read_text(errors="replace").splitlines():
        if line.startswith("::CHK_ENV::"):
            parts = line.removeprefix("::CHK_ENV::").split("\0")
            if len(parts) == 3:
                cert_paths = dict(zip(("cert", "key", "services_list"), parts, strict=True))
    return Installation(returncode, node_id, unit, cert_paths)
