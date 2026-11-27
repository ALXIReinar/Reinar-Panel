import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .config import CORE_BINARIES, REPO, Config
from .manifest import ManifestEntry, entry_errors, script_path


@dataclass(frozen=True)
class InstallContext:
    cfg: Config
    template_id: int
    node_id: int
    title: str


@dataclass(frozen=True)
class InstallStep:
    title: str
    command: str
    kind: Literal["env", "core", "acme", "node"]
    path: Path | None = None
    args: tuple[str, ...] = ()

    def render(self, relative: bool = False) -> str:
        if self.path is None:
            return self.command
        path = self.path
        if relative and path.is_relative_to(REPO):
            path = path.relative_to(REPO)
        return shlex.join([self.command, str(path), *self.args])


def build_steps(entry: ManifestEntry, ctx: InstallContext) -> list[InstallStep]:
    if entry.skip or not entry.install_script:
        raise ValueError(f"{entry.template}: установка пропущена ({entry.skip or 'нет скрипта'})")
    cfg = ctx.cfg
    errors = entry_errors(entry, cfg)
    if errors:
        raise ValueError(f"{entry.template}: {', '.join(errors)}")
    env = {
        "PROTO_ID": str(ctx.template_id),
        "NODE_ID": str(ctx.node_id),
        "ADMIN_PANEL_IP": cfg.admin_panel_ip_for_scripts,
        "ADMIN_PANEL_PORT": str(cfg.admin_panel_port_for_scripts),
        "TITLE": ctx.title,
    }
    domain, email = entry.domain or cfg.domain, entry.email or cfg.email
    if domain:
        env["DOMAIN"] = domain
    if email:
        env["EMAIL"] = email
    for key, value in entry.env.items():
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or key in env:
            raise ValueError(f"{entry.template}: недопустимое имя переменной {key}")
        env[key] = str(value)
    steps = [
        InstallStep(
            "Задать параметры установки",
            "export " + " ".join(f"{key}={shlex.quote(value)}" for key, value in env.items()),
            "env",
        )
    ]
    if not os.access(CORE_BINARIES[entry.core], os.X_OK):
        core_script = script_path(cfg.scripts_root, f"{entry.core.replace('-', '')}/install.sh")
        steps.append(InstallStep("Установить ядро", "bash", "core", core_script))
    if entry.tls:
        acme = script_path(cfg.scripts_root, "issue_cert_acme.sh")
        steps.append(InstallStep("Подготовить сертификат", "source", "acme", acme, (domain or "", email or "")))
    steps.append(
        InstallStep(
            "Установить виртуальную ноду",
            "bash",
            "node",
            script_path(cfg.scripts_root, entry.install_script),
            tuple(map(str, entry.args)),
        )
    )
    return steps


def render_manual(steps: list[InstallStep]) -> str:
    text = ["Выполните команды из корня репозитория в одной сессии Bash."]
    for step in steps:
        text.append(f"### {step.title}\n\n```bash\n{step.render(relative=True)}\n```")
    return "\n\n".join(text)


def render_session(steps: list[InstallStep]) -> str:
    commands = ["set -e"]
    for step in steps:
        commands.append(step.render())
        if step.kind == "acme":
            commands.append("""printf '::CHK_ENV::%s\\0%s\\0%s\\n' "$CERT_PATH" "$KEY_PATH" "$SERVICES_LIST" >&2""")
    return "\n".join(commands)
