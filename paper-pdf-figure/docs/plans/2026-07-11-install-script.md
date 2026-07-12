# Install Script Implementation Plan - paper-pdf-figures

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A one-click installer (`install.py` + `install.sh`) that takes the `dist/paper-pdf-figures-<ver>.skill` zip and installs the skill into a Claude Code skills directory, installs Python deps (basic + optional ML into a user-chosen Python env), and verifies via `check_deps.py`.

**Architecture:** `install.py` (Python, single file, function-per-concern) does all logic; `install.sh` (bash, ~10 lines) is a thin entry that calls `python3 install.py "$@"`. Interactive mode asks the user (target dir / existing-handling / ML install / ML env); `--yes` mode uses defaults. ML env detection reads `conda env list` + `sys.executable`. Reuses existing `install_deps.sh` (system deps) and `check_deps.py` (verification) unchanged.

**Tech Stack:** Python ≥3.9 (stdlib: argparse, zipfile, subprocess, pathlib, shutil, re, sys), pytest + jsonschema (already installed). No new runtime deps.

## Global Constraints

(From the spec `paper-pdf-figure/docs/designs/2026-07-11-install-script-design.md` - every task inherits these.)

- Skill root: `.claude/skills/paper-pdf-figures/`; tests run from there: `cd .claude/skills/paper-pdf-figures && pytest tests/ -v`
- `.skill` package is a zip with top-level dir `paper-pdf-figures/`; located at `dist/paper-pdf-figures-<version>.skill` (version from `VERSION` file).
- `find_package` default search: `<script_dir>/../../dist/paper-pdf-figures-*.skill` (script_dir is `.claude/skills/paper-pdf-figures/scripts/`, so `../../dist` = repo-root `dist/`).
- Install targets: user `~/.claude/skills/`, project `./.claude/skills/`, or custom path. The skill extracts to `<target>/paper-pdf-figures/`.
- Existing-dir handling: backup (rename to `paper-pdf-figures.bak`, default) / overwrite / cancel. Backup must not clobber an existing `.bak` (suffix `.bak2`, `.bak3`...).
- ML deps (`requirements-ml.txt`) install into a user-chosen Python env: current `sys.executable` / a conda env's python / a manually-entered venv python path. `pip_install(python, reqs)` runs `<python> -m pip install -r <reqs>`.
- `check_deps.py` output lines start with `[OK]` / `[WARN]` / `[MISSING]`; a line `All modes available.` means all 5 modes work; `Unavailable modes (missing required deps): ...` lists blocked modes.
- Reuse, do not modify: `scripts/install_deps.sh` (called for system deps), `scripts/check_deps.py` (called for verification), `requirements.txt` / `requirements-ml.txt`.
- Non-interactive flags: `--yes` (all defaults), `--package PATH`, `--target PATH`, `--ml`/`--no-ml`, `--ml-env PYTHON`, `--dry-run`.
- Each install step is independent try; single-step failure does not abort (user sees full diagnostic). Failures print actionable commands, not raw tracebacks.
- Offline after install; the installer itself does not need network (pip installs do).

---

## File Structure

| Path | Responsibility |
| --- | --- |
| `.claude/skills/paper-pdf-figures/scripts/install.py` | Main installer logic: package finding, target selection, existing-handling, extract, pip, env detection, verify, main/argparse |
| `.claude/skills/paper-pdf-figures/scripts/install.sh` | bash entry: `python3 install.py "$@"` |
| `.claude/skills/paper-pdf-figures/tests/test_install.py` | Unit tests for pure functions (find_package, detect_python_envs, parse_check_deps, handle_existing decision, prompt, extract backup/overwrite) |

`install_deps.sh`, `check_deps.py`, `requirements*.txt` unchanged.

---

## Task 1: install.py skeleton + find_package + prompt

**Files:**
- Create: `.claude/skills/paper-pdf-figures/scripts/install.py`
- Create: `.claude/skills/paper-pdf-figures/tests/test_install.py`

**Interfaces:**
- `install.find_package(package_arg: str | None, script_dir: Path) -> Path` - returns the .skill path: `package_arg` if given, else the single `paper-pdf-figures-*.skill` in `<script_dir>/../../../../dist/`, else raises `FileNotFoundError`. Errors if multiple match and none specified.
- `install.prompt(question: str, choices: list[str] | None, default: str | None, non_interactive: bool) -> str` - reads a line from stdin; returns default on empty input or `non_interactive`; if `choices` given, re-prompts until a valid choice.

- [ ] **Step 1: Write the failing tests**

File `.claude/skills/paper-pdf-figures/tests/test_install.py`:
```python
from pathlib import Path

import install


def test_find_package_explicit(tmp_path):
    pkg = tmp_path / "x.skill"
    pkg.write_bytes(b"PK")  # not a real zip, just a file
    assert install.find_package(str(pkg), tmp_path) == pkg


def test_find_package_default_single_match(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    pkg = dist / "paper-pdf-figures-0.1.0.skill"
    pkg.write_bytes(b"PK")
    # mirror real repo layout: scripts 4 levels deep
    scripts = tmp_path / ".claude" / "skills" / "paper-pdf-figures" / "scripts"
    scripts.mkdir(parents=True)
    assert install.find_package(None, scripts) == pkg


def test_find_package_none_raises(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    try:
        install.find_package(None, scripts)
        assert False, "should have raised"
    except FileNotFoundError:
        pass


def test_find_package_multiple_no_arg_raises(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "paper-pdf-figures-0.1.0.skill").write_bytes(b"PK")
    (dist / "paper-pdf-figures-0.2.0.skill").write_bytes(b"PK")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    try:
        install.find_package(None, scripts)
        assert False, "should have raised (ambiguous)"
    except FileNotFoundError:
        pass


def test_prompt_returns_default_on_empty(monkeypatch):
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("\n"))
    assert install.prompt("q?", default="1", non_interactive=False) == "1"


def test_prompt_non_interactive_returns_default():
    assert install.prompt("q?", default="yes", non_interactive=True) == "yes"


def test_prompt_validates_choices(monkeypatch):
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("bad\n2\n"))
    assert install.prompt("q?", choices=["1", "2"], default="1", non_interactive=False) == "2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_install.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'install'`.

- [ ] **Step 3: Write `scripts/install.py` (skeleton + find_package + prompt)**

File `.claude/skills/paper-pdf-figures/scripts/install.py`:
```python
#!/usr/bin/env python3
"""One-click installer for the paper-pdf-figures skill (.skill -> Claude Code)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def find_package(package_arg: str | None, script_dir: Path) -> Path:
    """Locate the .skill zip to install.

    package_arg if given (explicit path); else the single
    paper-pdf-figures-*.skill in <script_dir>/../../../../dist/. Raises
    FileNotFoundError if none or ambiguous.
    """
    if package_arg:
        p = Path(package_arg)
        if not p.is_file():
            raise FileNotFoundError(f"package not found: {package_arg}")
        return p
    # scripts/ -> paper-pdf-figures/ -> skills/ -> .claude/ -> <repo>/
    dist = script_dir.parent.parent.parent.parent / "dist"
    matches = sorted(dist.glob("paper-pdf-figures-*.skill"))
    if len(matches) == 0:
        raise FileNotFoundError(
            f"no paper-pdf-figures-*.skill found in {dist}; pass --package PATH")
    if len(matches) > 1:
        raise FileNotFoundError(
            f"multiple .skill packages in {dist}; pass --package to choose: "
            + ", ".join(m.name for m in matches))
    return matches[0]


def prompt(question: str, choices: list[str] | None = None,
           default: str | None = None, non_interactive: bool = False) -> str:
    """Read one line from stdin; return default on empty / non_interactive.

    If choices given, re-prompt until a valid choice (or default on empty).
    """
    if non_interactive:
        return default if default is not None else ""
    while True:
        suffix = f" [{default}]" if default else ""
        ans = input(f"{question}{suffix} ").strip()
        if not ans:
            return default if default is not None else ""
        if choices is None or ans in choices:
            return ans
        print(f"  invalid choice; pick one of {choices}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="install", description=__doc__)
    parser.add_argument("--yes", action="store_true", help="non-interactive, use defaults")
    parser.add_argument("--package", default=None)
    parser.add_argument("--target", default=None)
    parser.add_argument("--ml", action="store_true")
    parser.add_argument("--no-ml", action="store_true")
    parser.add_argument("--ml-env", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    print(f"(dry-run={args.dry_run}, yes={args.yes})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_install.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/scripts/install.py .claude/skills/paper-pdf-figures/tests/test_install.py
git commit -m "feat(paper-pdf-figures): install.py skeleton + find_package + prompt"
```

---

## Task 2: detect_python_envs + ask_ml_env

**Files:**
- Modify: `.claude/skills/paper-pdf-figures/scripts/install.py`
- Modify: `.claude/skills/paper-pdf-figures/tests/test_install.py`

**Interfaces:**
- `install.PythonEnv(name: str, python: Path, kind: str)` dataclass (`kind` in {"current","conda","venv"}).
- `install.detect_python_envs() -> list[PythonEnv]` - current `sys.executable` (kind "current") + conda envs (parse `conda env list` if `conda` on PATH) + a venv inferred from `$VIRTUAL_ENV` if set. Never raises; on any error returns just the current env.
- `install.ask_ml_env(envs: list[PythonEnv], default_idx: int, non_interactive: bool) -> Path` - interactive: list envs + "input other python path"; returns chosen python path. `non_interactive` -> envs[default_idx].python.

- [ ] **Step 1: Write the failing tests (append to test_install.py)**

```python
def test_detect_python_envs_includes_current():
    envs = install.detect_python_envs()
    assert len(envs) >= 1
    assert envs[0].kind == "current"
    assert envs[0].python.exists()


def test_detect_python_envs_parses_conda(monkeypatch):
    conda_out = (
        "# conda environments:\n"
        "#\n"
        "# * -> active\n"
        "base                 *   /home/u/anaconda3\n"
        "myenv                    /home/u/.conda/envs/myenv\n"
    )
    def fake_run(cmd, **kw):
        import subprocess
        return subprocess.CompletedProcess(cmd, 0, conda_out, "")
    monkeypatch.setattr(install.subprocess, "run", fake_run)
    monkeypatch.setattr(install.shutil, "which", lambda n: "/usr/bin/conda")
    envs = install.detect_python_envs()
    names = [e.name for e in envs]
    assert "conda:base" in names or any("base" in n for n in names)
    assert any("myenv" in n for n in names)
    # current is first
    assert envs[0].kind == "current"


def test_detect_python_envs_no_conda(monkeypatch):
    monkeypatch.setattr(install.shutil, "which", lambda n: None)
    envs = install.detect_python_envs()
    assert len(envs) == 1
    assert envs[0].kind == "current"


def test_ask_ml_env_non_interactive():
    envs = [install.PythonEnv("current", Path("/usr/bin/python3"), "current")]
    chosen = install.ask_ml_env(envs, default_idx=0, non_interactive=True)
    assert chosen == Path("/usr/bin/python3")


def test_ask_ml_env_interactive_pick(monkeypatch):
    envs = [
        install.PythonEnv("current", Path("/p/cur/python"), "current"),
        install.PythonEnv("conda:myenv", Path("/p/myenv/python"), "conda"),
    ]
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("2\n"))
    chosen = install.ask_ml_env(envs, default_idx=0, non_interactive=False)
    assert chosen == Path("/p/myenv/python")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_install.py -k "detect_python_envs or ask_ml_env" -v
```
Expected: FAIL (`PythonEnv`/`detect_python_envs`/`ask_ml_env` undefined).

- [ ] **Step 3: Add env detection to install.py**

Add imports at top of `install.py`:
```python
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
```

Add after `prompt`:
```python
@dataclass
class PythonEnv:
    name: str
    python: Path
    kind: str  # "current" | "conda" | "venv"


def detect_python_envs() -> list[PythonEnv]:
    """Detect available Python envs: current + conda envs + venv (VIRTUAL_ENV)."""
    envs: list[PythonEnv] = [PythonEnv("current", Path(sys.executable), "current")]
    # conda
    if shutil.which("conda"):
        try:
            res = subprocess.run(["conda", "env", "list"], capture_output=True,
                                 text=True, check=False)
            for line in res.stdout.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) >= 2 and not parts[0].startswith("#"):
                    name, path = parts[0], parts[1]
                    py = Path(path) / "bin" / "python"
                    envs.append(PythonEnv(f"conda:{name}", py, "conda"))
        except Exception:
            pass
    # venv
    ve = os.environ.get("VIRTUAL_ENV")
    if ve:
        py = Path(ve) / "bin" / "python"
        if py.exists():
            envs.append(PythonEnv(f"venv:{Path(ve).name}", py, "venv"))
    return envs


def ask_ml_env(envs: list[PythonEnv], default_idx: int, non_interactive: bool) -> Path:
    """Ask the user which Python env to install ML deps into. Returns python path."""
    if non_interactive or len(envs) == 1:
        return envs[default_idx].python
    print("  选择 Python 环境:")
    for i, e in enumerate(envs, 1):
        print(f"    {i}) {e.name} ({e.python})")
    print(f"    {len(envs)+1}) 输入其他 python 路径")
    raw = prompt(f"  选择", default=str(default_idx + 1), non_interactive=False)
    idx = int(raw) - 1
    if 0 <= idx < len(envs):
        return envs[idx].python
    # "other" -> ask for a path
    path = prompt("  python 路径", default=None, non_interactive=False)
    return Path(path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_install.py -k "detect_python_envs or ask_ml_env" -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/scripts/install.py .claude/skills/paper-pdf-figures/tests/test_install.py
git commit -m "feat(paper-pdf-figures): detect_python_envs + ask_ml_env (conda/venv)"
```

---

## Task 3: parse_check_deps + verify

**Files:**
- Modify: `.claude/skills/paper-pdf-figures/scripts/install.py`
- Modify: `.claude/skills/paper-pdf-figures/tests/test_install.py`

**Interfaces:**
- `install.DepStatus(name: str, status: str)` dataclass (`status` in {"ok","warn","missing"}).
- `install.parse_check_deps_output(text: str) -> tuple[list[DepStatus], list[str]]` - returns (deps, unavailable_modes). Parses `[OK] X` / `[WARN] X` / `[MISSING] X` lines + the `Unavailable modes (missing required deps): a, b` line (empty list if "All modes available.").
- `install.verify(skill_dir: Path) -> int` - runs `python3 check_deps.py`, parses, prints a 5-mode availability summary, returns check_deps exit code.

- [ ] **Step 1: Write the failing tests (append)**

```python
def test_parse_check_deps_all_ok():
    text = (
        "[OK] Python 3.13.9 (>=3.9 required)\n"
        "[OK] PyMuPDF\n[OK] torch\n[WARN] pdftocairo\n"
        "All modes available.\n"
    )
    deps, unavail = install.parse_check_deps_output(text)
    assert deps[0] == install.DepStatus("Python 3.13.9 (>=3.9 required)", "ok")
    assert deps[1] == install.DepStatus("PyMuPDF", "ok")
    assert deps[3] == install.DepStatus("pdftocairo", "warn")
    assert unavail == []


def test_parse_check_deps_missing_modes():
    text = (
        "[OK] PyMuPDF\n[MISSING] torch\n[MISSING] opencv-python\n"
        "Unavailable modes (missing required deps): auto, detect\n"
        "Note: pdftocairo missing - ...\n"
    )
    deps, unavail = install.parse_check_deps_output(text)
    assert deps[1] == install.DepStatus("torch", "missing")
    assert unavail == ["auto", "detect"]


def test_parse_check_deps_warn_not_missing():
    text = "[OK] PyMuPDF\n[WARN] pdftocairo\nAll modes available.\n"
    deps, unavail = install.parse_check_deps_output(text)
    assert deps[1].status == "warn"
    assert unavail == []


def test_verify_runs_check_deps(tmp_path):
    # make a fake skill dir with a check_deps.py that prints all-ok and exits 0
    skill = tmp_path / "paper-pdf-figures"
    (skill / "scripts").mkdir(parents=True)
    (skill / "scripts" / "check_deps.py").write_text(
        "print('[OK] PyMuPDF')\nprint('All modes available.')\n"
    )
    rc = install.verify(skill)
    assert rc == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_install.py -k "parse_check_deps or verify_runs" -v
```
Expected: FAIL (undefined).

- [ ] **Step 3: Add parsing + verify to install.py**

Add dataclass near `PythonEnv`:
```python
@dataclass
class DepStatus:
    name: str
    status: str  # "ok" | "warn" | "missing"
```

Add functions (after `ask_ml_env`):
```python
def parse_check_deps_output(text: str) -> tuple[list[DepStatus], list[str]]:
    """Parse check_deps.py stdout -> (deps, unavailable_modes)."""
    deps: list[DepStatus] = []
    unavail: list[str] = []
    for line in text.splitlines():
        if line.startswith("[OK] "):
            deps.append(DepStatus(line[5:].strip(), "ok"))
        elif line.startswith("[WARN] "):
            deps.append(DepStatus(line[7:].strip(), "warn"))
        elif line.startswith("[MISSING] "):
            deps.append(DepStatus(line[10:].strip(), "missing"))
        elif line.startswith("Unavailable modes (missing required deps):"):
            rest = line.split(":", 1)[1].strip()
            unavail = [m.strip() for m in rest.split(",") if m.strip()]
    return deps, unavail


def verify(skill_dir: Path) -> int:
    """Run check_deps.py in skill_dir, print a 5-mode summary, return exit code."""
    check = skill_dir / "scripts" / "check_deps.py"
    res = subprocess.run([sys.executable, str(check)], capture_output=True,
                         text=True, check=False, cwd=str(skill_dir))
    deps, unavail = parse_check_deps_output(res.stdout)
    print("  依赖状态:")
    for d in deps:
        mark = {"ok": "[OK]", "warn": "[WARN]", "missing": "[MISSING]"}[d.status]
        print(f"    {mark} {d.name}")
    modes = ["embedded", "manual", "detect", "render", "auto"]
    print("  模式可用性:")
    for m in modes:
        if m in unavail:
            print(f"    {m:10s} 不可用 (缺依赖)")
        else:
            print(f"    {m:10s} 可用")
    return res.returncode
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_install.py -k "parse_check_deps or verify_runs" -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/scripts/install.py .claude/skills/paper-pdf-figures/tests/test_install.py
git commit -m "feat(paper-pdf-figures): parse_check_deps + verify (5-mode summary)"
```

---

## Task 4: handle_existing + extract_package

**Files:**
- Modify: `.claude/skills/paper-pdf-figures/scripts/install.py`
- Modify: `.claude/skills/paper-pdf-figures/tests/test_install.py`

**Interfaces:**
- `install.handle_existing(target_skill_dir: Path, non_interactive: bool) -> str` - returns "backup" / "overwrite" / "cancel". If target doesn't exist -> "install" (fresh). Default on existing: "backup".
- `install.extract_package(pkg: Path, target_skills_dir: Path, action: str, dry_run: bool) -> Path` - extracts zip (top-level `paper-pdf-figures/`) to target_skills_dir. For "backup": rename existing `paper-pdf-figures/` to `paper-pdf-figures.bak` (`.bak2`, `.bak3`... if taken) first. For "overwrite": rm -rf existing first. For "cancel": no-op. Returns the extracted skill dir path.

- [ ] **Step 1: Write the failing tests (append)**

```python
def test_handle_existing_fresh(tmp_path):
    target = tmp_path / "paper-pdf-figures"
    assert install.handle_existing(target, non_interactive=True) == "install"


def test_handle_existing_backup_default(tmp_path):
    target = tmp_path / "paper-pdf-figures"
    target.mkdir()
    (target / "SKILL.md").write_text("old")
    assert install.handle_existing(target, non_interactive=True) == "backup"


def test_extract_package_fresh(tmp_path):
    import zipfile
    pkg = tmp_path / "test.skill"
    with zipfile.ZipFile(pkg, "w") as z:
        z.writestr("paper-pdf-figures/SKILL.md", "hello")
        z.writestr("paper-pdf-figures/VERSION", "0.1.0")
    target_skills = tmp_path / "skills"
    target_skills.mkdir()
    skill_dir = install.extract_package(pkg, target_skills, "install", dry_run=False)
    assert (skill_dir / "SKILL.md").read_text() == "hello"
    assert (skill_dir / "VERSION").read_text() == "0.1.0"


def test_extract_package_backup_existing(tmp_path):
    import zipfile
    pkg = tmp_path / "test.skill"
    with zipfile.ZipFile(pkg, "w") as z:
        z.writestr("paper-pdf-figures/SKILL.md", "new")
    target_skills = tmp_path / "skills"
    old_skill = target_skills / "paper-pdf-figures"
    old_skill.mkdir(parents=True)
    (old_skill / "SKILL.md").write_text("old")
    skill_dir = install.extract_package(pkg, target_skills, "backup", dry_run=False)
    assert (skill_dir / "SKILL.md").read_text() == "new"
    # old backed up
    assert (target_skills / "paper-pdf-figures.bak" / "SKILL.md").read_text() == "old"


def test_extract_package_backup_no_clobber(tmp_path):
    import zipfile
    pkg = tmp_path / "test.skill"
    with zipfile.ZipFile(pkg, "w") as z:
        z.writestr("paper-pdf-figures/SKILL.md", "new")
    target_skills = tmp_path / "skills"
    old = target_skills / "paper-pdf-figures"; old.mkdir(parents=True)
    (old / "SKILL.md").write_text("old1")
    bak = target_skills / "paper-pdf-figures.bak"; bak.mkdir()
    (bak / "SKILL.md").write_text("old0")
    skill_dir = install.extract_package(pkg, target_skills, "backup", dry_run=False)
    assert (target_skills / "paper-pdf-figures.bak2" / "SKILL.md").read_text() == "old1"


def test_extract_package_overwrite(tmp_path):
    import zipfile
    pkg = tmp_path / "test.skill"
    with zipfile.ZipFile(pkg, "w") as z:
        z.writestr("paper-pdf-figures/SKILL.md", "new")
    target_skills = tmp_path / "skills"
    old = target_skills / "paper-pdf-figures"; old.mkdir(parents=True)
    (old / "SKILL.md").write_text("old")
    (old / "extra.txt").write_text("x")
    skill_dir = install.extract_package(pkg, target_skills, "overwrite", dry_run=False)
    assert (skill_dir / "SKILL.md").read_text() == "new"
    assert not (skill_dir / "extra.txt").exists()


def test_extract_package_dry_run(tmp_path):
    import zipfile
    pkg = tmp_path / "test.skill"
    with zipfile.ZipFile(pkg, "w") as z:
        z.writestr("paper-pdf-figures/SKILL.md", "new")
    target_skills = tmp_path / "skills"; target_skills.mkdir()
    install.extract_package(pkg, target_skills, "install", dry_run=True)
    assert not (target_skills / "paper-pdf-figures").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_install.py -k "handle_existing or extract_package" -v
```
Expected: FAIL (undefined).

- [ ] **Step 3: Add handle_existing + extract_package to install.py**

Add imports `import zipfile` and `import shutil` (shutil already imported in Task 2). Add functions after `verify`:
```python
def handle_existing(target_skill_dir: Path, non_interactive: bool) -> str:
    """Decide what to do with an existing install. Returns
    'install' (none) / 'backup' / 'overwrite' / 'cancel'."""
    if not target_skill_dir.exists():
        return "install"
    if non_interactive:
        return "backup"
    print(f"  目标已有 {target_skill_dir.name}/，如何处理？")
    print("    1) 备份后安装 (重命名 .bak)  <- 默认")
    print("    2) 覆盖")
    print("    3) 取消")
    raw = prompt("  选择", default="1", non_interactive=False)
    return {"1": "backup", "2": "overwrite", "3": "cancel"}.get(raw, "backup")


def _next_backup_name(base: Path) -> Path:
    """Find a non-clobbering backup name: .bak, .bak2, .bak3..."""
    cand = base.with_name(base.name + ".bak")
    i = 2
    while cand.exists():
        cand = base.with_name(f"{base.name}.bak{i}")
        i += 1
    return cand


def extract_package(pkg: Path, target_skills_dir: Path,
                    action: str, dry_run: bool) -> Path:
    """Extract the .skill zip to target_skills_dir. Returns the skill dir."""
    skill_dir = target_skills_dir / "paper-pdf-figures"
    if dry_run:
        print(f"  [dry-run] would extract {pkg.name} -> {skill_dir} (action={action})")
        return skill_dir
    if action == "cancel":
        print("  取消。")
        return skill_dir
    target_skills_dir.mkdir(parents=True, exist_ok=True)
    if action == "backup" and skill_dir.exists():
        bak = _next_backup_name(skill_dir)
        skill_dir.rename(bak)
        print(f"  已备份旧版 -> {bak.name}")
    elif action == "overwrite" and skill_dir.exists():
        shutil.rmtree(skill_dir)
    with zipfile.ZipFile(pkg) as z:
        z.extractall(target_skills_dir)
    print(f"  解压完成 -> {skill_dir}")
    return skill_dir
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_install.py -k "handle_existing or extract_package" -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/scripts/install.py .claude/skills/paper-pdf-figures/tests/test_install.py
git commit -m "feat(paper-pdf-figures): handle_existing + extract_package (backup/overwrite)"
```

---

## Task 5: pip_install + install_system_deps + main wiring + install.sh

**Files:**
- Modify: `.claude/skills/paper-pdf-figures/scripts/install.py`
- Modify: `.claude/skills/paper-pdf-figures/tests/test_install.py`
- Create: `.claude/skills/paper-pdf-figures/scripts/install.sh`

**Interfaces:**
- `install.pip_install(python: Path, reqs_file: Path, dry_run: bool) -> bool` - runs `<python> -m pip install -r <reqs>`; returns True on success, False on failure (prints error + suggestion, does not raise).
- `install.install_system_deps(script_dir: Path, dry_run: bool) -> None` - calls existing `install_deps.sh` (in script_dir) via bash; no sudo handling (install_deps.sh does it). Best-effort.
- `install.main(argv)` - full wiring: argparse + find_package + ask_target + handle_existing + extract + pip basic + (ask ML + ask_ml_env + pip ML) + install_system_deps + verify.
- `install.ask_target(non_interactive, target_arg) -> Path` - returns target skills/ dir.

- [ ] **Step 1: Write the failing tests (append)**

```python
def test_pip_install_success(tmp_path, monkeypatch):
    def fake_run(cmd, **kw):
        import subprocess
        return subprocess.CompletedProcess(cmd, 0, "installed", "")
    monkeypatch.setattr(install.subprocess, "run", fake_run)
    reqs = tmp_path / "requirements.txt"; reqs.write_text("foo")
    ok = install.pip_install(Path("/usr/bin/python3"), reqs, dry_run=False)
    assert ok is True


def test_pip_install_failure(tmp_path, monkeypatch):
    def fake_run(cmd, **kw):
        import subprocess
        return subprocess.CompletedProcess(cmd, 1, "", "some pip error")
    monkeypatch.setattr(install.subprocess, "run", fake_run)
    reqs = tmp_path / "requirements.txt"; reqs.write_text("foo")
    ok = install.pip_install(Path("/usr/bin/python3"), reqs, dry_run=False)
    assert ok is False


def test_pip_install_dry_run(tmp_path):
    reqs = tmp_path / "requirements.txt"; reqs.write_text("foo")
    ok = install.pip_install(Path("/usr/bin/python3"), reqs, dry_run=True)
    assert ok is True  # dry-run always "succeeds"


def test_ask_target_non_interactive_default():
    import os
    home = os.path.expanduser("~")
    t = install.ask_target(non_interactive=True, target_arg=None)
    assert t == Path(home) / ".claude" / "skills"


def test_ask_target_explicit(tmp_path):
    t = install.ask_target(non_interactive=True, target_arg=str(tmp_path))
    assert t == tmp_path
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_install.py -k "pip_install or ask_target" -v
```
Expected: FAIL (undefined).

- [ ] **Step 3: Add pip_install + ask_target + install_system_deps + wire main**

Add to install.py (after `extract_package`):
```python
def pip_install(python: Path, reqs_file: Path, dry_run: bool) -> bool:
    """Run <python> -m pip install -r <reqs>. Returns True on success."""
    if dry_run:
        print(f"  [dry-run] {python} -m pip install -r {reqs_file.name}")
        return True
    print(f"  安装 {reqs_file.name} -> {python}")
    res = subprocess.run([str(python), "-m", "pip", "install", "-r", str(reqs_file)],
                        capture_output=False, check=False)
    if res.returncode != 0:
        print(f"  ERROR: pip install 失败 ({reqs_file.name})。手动尝试:", file=sys.stderr)
        print(f"    {python} -m pip install -r {reqs_file}", file=sys.stderr)
        return False
    return True


def install_system_deps(script_dir: Path, dry_run: bool) -> None:
    """Call existing install_deps.sh for system deps (apt poppler). Best-effort."""
    sh = script_dir / "install_deps.sh"
    if not sh.is_file():
        return
    if dry_run:
        print(f"  [dry-run] bash {sh.name}")
        return
    subprocess.run(["bash", str(sh)], check=False)


def ask_target(non_interactive: bool, target_arg: str | None) -> Path:
    """Return the target skills/ directory."""
    if target_arg:
        return Path(target_arg)
    if non_interactive:
        return Path.home() / ".claude" / "skills"
    print("[1] 安装目标")
    print("  1) 用户级 (~/.claude/skills/)  <- 默认")
    print("  2) 项目级 (./.claude/skills/)")
    print("  3) 自定义路径")
    raw = prompt("  选择", default="1", non_interactive=False)
    if raw == "2":
        return Path(".claude/skills")
    if raw == "3":
        p = prompt("  路径", default=None, non_interactive=False)
        return Path(p)
    return Path.home() / ".claude" / "skills"
```

Replace the existing `main` (the Task 1 stub) with the full wiring:
```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="install", description=__doc__)
    parser.add_argument("--yes", action="store_true", help="non-interactive, use defaults")
    parser.add_argument("--package", default=None)
    parser.add_argument("--target", default=None)
    parser.add_argument("--ml", action="store_true")
    parser.add_argument("--no-ml", action="store_true")
    parser.add_argument("--ml-env", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    script_dir = Path(__file__).resolve().parent
    skill_root = script_dir.parent

    print("paper-pdf-figures 安装程序")
    print("=" * 40)
    try:
        pkg = find_package(args.package, script_dir)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"找到包: {pkg}")

    target = ask_target(args.yes, args.target)
    target_skill = target / "paper-pdf-figures"
    action = handle_existing(target_skill, args.yes)
    if action == "cancel":
        print("取消。")
        return 0

    print("\n[2] 解压安装")
    skill_dir = extract_package(pkg, target, action, args.dry_run)
    if args.dry_run:
        # dry-run: skip pip/verify (skill not actually extracted)
        print("\n[dry-run] 跳过依赖安装与验证")
        return 0

    print("\n[3] 基础依赖 (requirements.txt)")
    basic_reqs = skill_root / "requirements.txt"
    if not basic_reqs.is_file():
        basic_reqs = skill_dir / "requirements.txt"
    ok = pip_install(Path(sys.executable), basic_reqs, args.dry_run)

    print("\n[4] ML 依赖 (auto 模式)")
    do_ml = args.ml
    if args.no_ml:
        do_ml = False
    elif not args.yes:
        ans = prompt("  是否安装 ML 依赖 (torch+doclayout-yolo, 约2GB)? [y/N]",
                     default="n", non_interactive=False)
        do_ml = ans.lower() in ("y", "yes")
    if do_ml:
        ml_reqs = skill_root / "requirements-ml.txt"
        if not ml_reqs.is_file():
            ml_reqs = skill_dir / "requirements-ml.txt"
        if args.ml_env:
            ml_python = Path(args.ml_env)
        else:
            envs = detect_python_envs()
            ml_python = ask_ml_env(envs, default_idx=0, non_interactive=args.yes)
        pip_install(ml_python, ml_reqs, args.dry_run)

    print("\n[5] 系统依赖 (poppler)")
    install_system_deps(script_dir, args.dry_run)

    print("\n[6] 验证")
    verify(skill_dir)
    print("\n安装完成! 用法:")
    print(f"  {skill_dir}/scripts/extract_pdf_figures.py paper.pdf --mode auto --out ./out")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_install.py -k "pip_install or ask_target" -v
pytest tests/ -q -k "not real_doclayout"
```
Expected: 5 new tests pass; full suite green (was 143 + install tests so far).

- [ ] **Step 5: Create install.sh**

File `.claude/skills/paper-pdf-figures/scripts/install.sh`:
```bash
#!/usr/bin/env bash
# One-click installer entry for paper-pdf-figures.
# Usage: bash install.sh [--yes] [--package PATH] [--target PATH] [--ml|--no-ml] [--ml-env PYTHON] [--dry-run]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/install.py" "$@"
```

- [ ] **Step 6: Make install.sh executable + smoke test --dry-run**

Run:
```bash
cd /home/imalne/learn_vibe_coding
chmod +x .claude/skills/paper-pdf-figures/scripts/install.sh
bash .claude/skills/paper-pdf-figures/scripts/install.sh --yes --dry-run
```
Expected: exit 0, prints the dry-run plan (found package, target, would extract, skip deps).

- [ ] **Step 7: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/scripts/install.py .claude/skills/paper-pdf-figures/scripts/install.sh .claude/skills/paper-pdf-figures/tests/test_install.py
git commit -m "feat(paper-pdf-figures): pip_install + main wiring + install.sh entry"
```

---

## Task 6: Real smoke test (interactive + non-interactive) + docs

**Files:**
- (no code) manual smoke
- Modify: `.claude/skills/paper-pdf-figures/README.md` (add install instructions)

- [ ] **Step 1: Non-interactive smoke (install to a temp dir, no ML)**

Run:
```bash
cd /home/imalne/learn_vibe_coding
TMP=$(mktemp -d)
bash .claude/skills/paper-pdf-figures/scripts/install.sh --yes --target "$TMP/skills" --no-ml
echo "exit=$?"
ls "$TMP/skills/paper-pdf-figures/SKILL.md" && echo "skill installed"
python3 "$TMP/skills/paper-pdf-figures/scripts/check_deps.py" | grep -E "OK|WARN|MISS" | head -3
rm -rf "$TMP"
```
Expected: exit 0, skill extracted, check_deps runs (PyMuPDF OK since deps already installed globally).

- [ ] **Step 2: Verify acceptance**
- A1: `--yes --target --no-ml` installs without prompting.
- A2: skill extracted to target with SKILL.md + scripts/.
- A3: `check_deps.py` runs from the installed location.
- A4: `--dry-run` prints plan without writing.

- [ ] **Step 3: Update README install instructions**

In `.claude/skills/paper-pdf-figures/README.md`, replace the existing `## Install` section with:
```markdown
## Install

### From the .skill package (one-click)

```bash
# interactive (asks target, ML, env)
bash scripts/install.sh
# or non-interactive
bash scripts/install.sh --yes --target ~/.claude/skills --no-ml
```

### Manual

```bash
pip install -r requirements.txt           # required (all modes)
pip install -r requirements-ml.txt        # optional (auto mode)
bash scripts/install_deps.sh              # system deps (poppler)
python3 scripts/check_deps.py            # verify
```
```

- [ ] **Step 4: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/README.md
git commit -m "docs(paper-pdf-figures): install.sh one-click instructions in README"
```

---

## Self-Review Notes

**Spec coverage:**
- find_package (§4) -> Task 1.
- ask_target (§4) -> Task 5.
- handle_existing (§4) -> Task 4.
- extract_package (§4) -> Task 4.
- detect_python_envs (§4) -> Task 2.
- ask_ml_install + ask_ml_env (§4) -> Task 2 (ask_ml_env) + Task 5 (main asks ML).
- pip_install (§4) -> Task 5.
- install_system_deps (§4) -> Task 5.
- verify (§4) -> Task 3.
- Non-interactive flags (§6) -> Task 1 (argparse) + Task 5 (main wiring).
- Edge cases (§7) -> Task 4 (backup no-clobber, cancel) + Task 5 (pip failure returns False).
- Tests (§9) -> each task has its unit tests.

**Placeholder scan:** none - every step has complete code.

**Type consistency:** `find_package -> Path`, `ask_target -> Path`, `handle_existing -> str` ("install"/"backup"/"overwrite"/"cancel"), `extract_package -> Path`, `detect_python_envs -> list[PythonEnv]`, `ask_ml_env -> Path`, `pip_install -> bool`, `verify -> int`. `PythonEnv(name, python, kind)` and `DepStatus(name, status)` consistent across tasks. `parse_check_deps_output -> tuple[list[DepStatus], list[str]]` matches verify's usage.

**Backward compat:** no existing files modified except README (docs) and the Task 1 `main` stub (replaced in Task 5). `install_deps.sh`/`check_deps.py`/requirements unchanged.
