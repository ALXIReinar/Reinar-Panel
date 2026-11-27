import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Listener:
    address: str
    port: int
    pids: set[int]
    raw: str


class OperatingSystem:
    def __init__(self, timeout: int):
        self.timeout = timeout

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(args, capture_output=True, text=True, timeout=self.timeout, check=check)
        except (OSError, subprocess.SubprocessError) as exc:
            label = " ".join(args[:2]) if args[0] != "bash" else "bash"
            raise RuntimeError(f"Ошибка команды {label} ({type(exc).__name__})") from None

    def systemctl(self, action: str, unit: str, *options: str, check: bool = True) -> str:
        return self.run("systemctl", action, *options, "--", unit, check=check).stdout

    def show(self, unit: str, *properties: str) -> dict[str, str]:
        result = self.systemctl("show", unit, "--property=" + ",".join(properties))
        return dict(line.split("=", 1) for line in result.splitlines() if "=" in line)

    def stable(self, unit: str, window: int) -> tuple[bool, dict]:
        properties = ("ActiveState", "MainPID", "NRestarts")
        before = self.show(unit, *properties)
        time.sleep(window)
        after = self.show(unit, *properties)
        stable = before == after and after.get("ActiveState") == "active" and int(after.get("MainPID", 0)) > 0
        return stable, {"before": before, "after": after, "seconds": window}

    def listeners(self) -> list[Listener]:
        result = []
        for line in self.run("ss", "-lntupH").stdout.splitlines():
            fields = line.split(maxsplit=6)
            if len(fields) < 6:
                continue
            address, _, port = fields[4].rpartition(":")
            if port.isdigit():
                result.append(
                    Listener(address.strip("[]"), int(port), set(map(int, re.findall(r"pid=(\d+)", line))), line)
                )
        return result

    def cgroup_pids(self, unit: str) -> set[int]:
        group = self.show(unit, "ControlGroup").get("ControlGroup")
        if not group or group == "/":
            return set()
        path = Path("/sys/fs/cgroup") / group.lstrip("/") / "cgroup.procs"
        try:
            return set(map(int, path.read_text().split()))
        except FileNotFoundError:
            return set()

    def journal(self, unit: str, since: datetime, limit: int = 200) -> str:
        return self.run(
            "journalctl", "-u", unit, "--no-pager", "--since", f"@{int(since.timestamp())}", "-n", str(limit)
        ).stdout
