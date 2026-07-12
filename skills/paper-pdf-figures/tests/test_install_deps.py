import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "install_deps.sh"


def test_dry_run_prints_plan_and_exits_zero():
    result = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "[dry-run]" in result.stdout
    assert "pip install" in result.stdout
    assert "poppler-utils" in result.stdout
