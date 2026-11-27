from pathlib import Path

from .results import read_results


def uncovered(runs: Path, scripts: Path) -> list[str]:
    passed = {row.get("install_script") for row in read_results(runs) if row["s1"]["status"] == "ok"}
    return sorted(
        str(path.relative_to(scripts))
        for path in scripts.glob("*/*/**/*.sh")
        if path.is_file() and str(path.relative_to(scripts)) not in passed
    )
