import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import Config

ALIASES = {"shadowsocks": "ss", "hysteria2": "hy2", "tuic": "tuicv5"}
HEADER = """# template: имя в proto_templates; install_script: путь от scripts_root.
# core: каталог ядра; tls: нужен сертификат; cdn: нужен порт 443 и подтверждение DNS/CDN.
# skip: причина пропуска; domain/email: переопределение настроек; args/env: параметры установки.
"""


@dataclass(frozen=True)
class ManifestEntry:
    template: str
    install_script: str | None
    core: str
    tls: bool
    cdn: bool
    skip: str = ""
    domain: str | None = None
    email: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict):
        template = data["template"]
        script = data.get("install_script")
        core = data.get("core", template.split("-")[0])
        tls = data.get("tls", bool(script and "tls" in Path(script).stem))
        cdn = data.get("cdn", bool(tls and script and {"ws", "httpupgrade"} & set(Path(script).stem.split("-"))))
        skip = data.get("skip", "")
        skip = phase_skip(template, core, script) or skip
        args = data.get("args", [])
        env = data.get("env", {})
        if not re.fullmatch(r"[a-z0-9-]+", core) or type(tls) is not bool or type(cdn) is not bool:
            raise ValueError(f"{template}: неверное значение core, tls или cdn")
        if not isinstance(args, list) or not isinstance(env, dict):
            raise ValueError(f"{template}: args должен быть списком, env — словарём")
        return cls(template, script, core, tls, cdn, skip, data.get("domain"), data.get("email"), args, env)


def load_raw(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError("Манифест должен содержать список записей")
    if any(not isinstance(item, dict) or not isinstance(item.get("template"), str) for item in data):
        raise ValueError("У каждой записи манифеста должно быть строковое поле template")
    return data


def load(path: Path) -> list[ManifestEntry]:
    return [ManifestEntry.from_mapping(item) for item in load_raw(path)]


def save(path: Path, records: list[dict]) -> None:
    text = yaml.safe_dump(sorted(records, key=lambda item: item["template"]), allow_unicode=True, sort_keys=False)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(HEADER + text, encoding="utf-8")
    temporary.replace(path)


def script_path(root: Path, value: str) -> Path:
    path = Path(value)
    resolved = (root / path).resolve()
    if path.is_absolute() or ".." in path.parts or not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"Ожидался путь внутри scripts_root: {value}")
    if not resolved.is_file() or resolved.suffix != ".sh":
        raise ValueError(f"Скрипт не найден: {value}")
    return resolved


def protocol_dir(template: str, scripts_root: Path) -> Path | None:
    parts = template.split("-")
    if len(parts) < 2 or any(not re.fullmatch(r"[a-z0-9_]+", part) for part in parts):
        return None
    core, proto = parts[:2]
    return scripts_root / core / ALIASES.get(proto, proto)


def candidates(template: str, scripts_root: Path) -> list[Path]:
    folder = protocol_dir(template, scripts_root)
    if folder is None:
        return []
    expected = set(template.split("-")[2:])
    return sorted(path for path in folder.glob("*.sh") if set(path.stem.split("-")) == expected and path.is_file())


def phase_skip(template: str, core: str, script: str | None) -> str:
    if core not in {"xray", "singbox"}:
        return "core_out_of_phase"
    if {"wg", "awg"} & set(template.split("-")):
        return "wg_awg_deferred"
    if script and "anti-censorship" in Path(script).parts:
        return "needs_two_servers"
    return ""


def choose_script(template: str, root: Path, matches: list[Path]) -> str | None:
    folder = protocol_dir(template, root)
    options = [] if folder is None else sorted([*folder.glob("*.sh"), *folder.glob("anti-censorship/*.sh")])
    print(f"{template} — совпадений по имени: {len(matches)}.")
    for option in options:
        print(f"  {option.relative_to(root)}")
    while True:
        try:
            value = input("Путь относительно scripts_root или s для пропуска: ").strip()
        except EOFError:
            return None
        if value == "s":
            return None
        try:
            script_path(root, value)
        except ValueError as exc:
            print(exc)
        else:
            return value


def generate(path: Path, titles: list[str], root: Path, no_prompt: bool) -> tuple[list[dict], list[str]]:
    records = load_raw(path) if path.exists() else []
    existing = {record["template"] for record in records}
    added = []
    for title in sorted(set(titles) - existing):
        core = title.split("-")[0]
        matches = candidates(title, root)
        skip = phase_skip(title, core, None)
        script = None
        if len(matches) == 1:
            script = str(matches[0].relative_to(root))
        elif not skip and not no_prompt:
            script = choose_script(title, root, matches)
        skip = phase_skip(title, core, script) or ("" if script else "unresolved")
        entry = ManifestEntry.from_mapping({"template": title, "install_script": script, "core": core, "skip": skip})
        added.append(dict(template=title, install_script=script, core=core, tls=entry.tls, cdn=entry.cdn, skip=skip))
    if added or not path.exists():
        save(path, records + added)
    return added, sorted(existing - set(titles))


def entry_errors(entry: ManifestEntry, cfg: Config) -> list[str]:
    if not entry.install_script:
        return [] if entry.skip else ["не задан install_script"]
    try:
        path = script_path(cfg.scripts_root, entry.install_script)
    except ValueError as exc:
        return [str(exc)]
    errors = []
    uses_tls = bool(re.search(r"\b(?:CERT_PATH|KEY_PATH)\b", path.read_text(encoding="utf-8")))
    if entry.tls != uses_tls:
        errors.append("tls не соответствует использованию CERT_PATH/KEY_PATH")
    if entry.tls and not entry.skip and not ((entry.domain or cfg.domain) and (entry.email or cfg.email)):
        errors.append("для TLS нужны domain и email")
    if entry.cdn and not entry.tls:
        errors.append("для CDN требуется tls")
    return errors


def lint(entries: list[ManifestEntry], titles: set[str], cfg: Config) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        issues = entry_errors(entry, cfg)
        if entry.template in seen:
            issues.append("повторная запись")
        if entry.template not in titles:
            issues.append("шаблон отсутствует в БД")
        if not entry.skip and not (cfg.scripts_root / entry.core.replace("-", "") / "install.sh").is_file():
            warnings.append(f"{entry.template}: отсутствует скрипт установки ядра")
        seen.add(entry.template)
        errors.extend(f"{entry.template}: {issue}" for issue in issues)
    return errors, warnings


def find(entries: list[ManifestEntry], template: str) -> ManifestEntry:
    matched = [entry for entry in entries if entry.template == template]
    if len(matched) != 1:
        raise ValueError(f"{template}: ожидалась одна запись манифеста, найдено {len(matched)}")
    return matched[0]
