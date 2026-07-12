# Install Script Fix: ML Env Coherence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the install script so that when the user specifies an ML Python env different from the installer's current Python, both basic and ML deps install into that env, and verify uses that env's Python to check_deps.

**Architecture:** Two changes: (1) `verify()` gains a `python: Path` parameter (default `sys.executable` for backward compat); `main()` passes the runtime Python (ML env if chosen, else current). (2) `main()` installs basic deps to the ML env when ML is enabled and `ml_python != sys.executable` (prints a clear message about dual install).

**Tech Stack:** Python ≥3.9, pytest (already installed). No new deps.

## Global Constraints

- Skill root: `.claude/skills/paper-pdf-figures/`; tests run from there.
- `verify(skill_dir, python=sys.executable) -> int` - backward-compatible default; callers that don't pass `python` still work.
- When ML is enabled and `ml_python` differs from `sys.executable`, basic deps ALSO install to `ml_python` (not just ML deps). Print a clear "安装到 ML 环境" message for both.
- When ML is disabled or `ml_python == sys.executable`, behavior is unchanged (basic -> current python, verify -> current python).
- `verify()` runs `check_deps.py` via the specified `python` (not hardcoded `sys.executable`), so ML deps are checked in the right env.
- The final usage hint in `main()` prints the correct python to use: if ML env was chosen, print `<ml_python> extract_pdf_figures.py ...` (not `python3 ...`).
- Tests mock `subprocess.run` to verify which Python is used for basic deps, ML deps, and verify.
- Do NOT change `pip_install` / `find_package` / `extract_package` / `handle_existing` / `detect_python_envs` / `ask_ml_env` signatures. Only `verify` gains a param and `main` changes its calls.

---

## File Structure

| Path | Change |
| --- | --- |
| `.claude/skills/paper-pdf-figures/scripts/install.py` | `verify` gains `python` param; `main` threads `ml_python` to basic+ML+verify |
| `.claude/skills/paper-pdf-figures/tests/test_install.py` | +tests for verify with python param; +test for basic-to-ML-env flow |

---

## Task 1: verify gains python param + main threads runtime Python

**Files:**
- Modify: `.claude/skills/paper-pdf-figures/scripts/install.py`
- Modify: `.claude/skills/paper-pdf-figures/tests/test_install.py`

**Interfaces:**
- `verify(skill_dir: Path, python: Path = None) -> int` - if `python` is None, defaults to `Path(sys.executable)` (backward compat). Runs `<python> check_deps.py`.
- `main()` logic change: determine `runtime_python` = `ml_python` if `do_ml` and `ml_python != sys.executable`, else `sys.executable`. Install basic deps to `runtime_python` (was `sys.executable`). Install ML deps to `ml_python` (unchanged). Call `verify(skill_dir, runtime_python)` (was `verify(skill_dir)`). Print final usage with `runtime_python`.

- [ ] **Step 1: Write failing tests (append to test_install.py)**

```python
def test_verify_uses_specified_python(tmp_path, monkeypatch):
    """verify() must run check_deps with the given python, not sys.executable."""
    skill = tmp_path / "paper-pdf-figures"
    (skill / "scripts").mkdir(parents=True)
    (skill / "scripts" / "check_deps.py").write_text(
        "print('[OK] PyMuPDF')\nprint('All modes available.')\n"
    )
    captured_cmd = []
    import subprocess
    def fake_run(cmd, **kw):
        captured_cmd.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "[OK] PyMuPDF\nAll modes available.\n", "")
    monkeypatch.setattr(install.subprocess, "run", fake_run)
    rc = install.verify(skill, python=Path("/custom/python3"))
    assert rc == 0
    # first arg of the command should be the custom python
    assert captured_cmd[0][0] == "/custom/python3"


def test_verify_defaults_to_sys_executable(tmp_path, monkeypatch):
    """verify() with python=None uses sys.executable (backward compat)."""
    skill = tmp_path / "paper-pdf-figures"
    (skill / "scripts").mkdir(parents=True)
    (skill / "scripts" / "check_deps.py").write_text("print('[OK]')\nprint('All modes available.')\n")
    import subprocess
    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, "[OK]\nAll modes available.\n", "")
    monkeypatch.setattr(install.subprocess, "run", fake_run)
    rc = install.verify(skill)  # no python kwarg
    assert rc == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_install.py -k "verify_uses_specified or verify_defaults" -v
```
Expected: FAIL (`verify` doesn't accept `python` kwarg -> `TypeError`).

- [ ] **Step 3: Modify verify + main in install.py**

a) Change `verify` signature + subprocess call:
```python
def verify(skill_dir: Path, python: Path = None) -> int:
    """Run check_deps.py in skill_dir, print a 5-mode summary, return exit code."""
    if python is None:
        python = Path(sys.executable)
    skill_dir = skill_dir.resolve()
    check = skill_dir / "scripts" / "check_deps.py"
    res = subprocess.run([str(python), str(check)], capture_output=True,
                         text=True, check=False, cwd=str(skill_dir))
```
(rest of verify unchanged)

b) In `main()`, replace the basic deps + ML + verify section (lines ~303-338). The new logic:

```python
    print("\n[3] ML 依赖 (auto 模式)")
    do_ml = args.ml
    if args.no_ml:
        do_ml = False
    elif not args.yes:
        ans = prompt("  是否安装 ML 依赖 (torch+doclayout-yolo, 约2GB)? [y/N]",
                     default="n", non_interactive=False)
        do_ml = ans.lower() in ("y", "yes")
    ml_python = None
    if do_ml:
        ml_reqs = skill_root / "requirements-ml.txt"
        if not ml_reqs.is_file():
            ml_reqs = skill_dir / "requirements-ml.txt"
        if args.ml_env:
            ml_python = Path(args.ml_env)
        else:
            envs = detect_python_envs()
            ml_python = ask_ml_env(envs, default_idx=0, non_interactive=args.yes)

    # Determine the runtime Python: ML env if chosen and different, else current.
    runtime_python = Path(sys.executable)
    if do_ml and ml_python and ml_python != Path(sys.executable):
        runtime_python = ml_python
        print(f"\n[4] 基础+ML 依赖均安装到 ML 环境: {runtime_python}")
    else:
        print(f"\n[4] 基础依赖 (requirements.txt)")

    # Install basic deps to runtime_python
    basic_reqs = skill_root / "requirements.txt"
    if not basic_reqs.is_file():
        basic_reqs = skill_dir / "requirements.txt"
    ok = pip_install(runtime_python, basic_reqs, args.dry_run)
    if not ok:
        print("  警告: 基础依赖安装失败,继续后续步骤", file=sys.stderr)

    # Install ML deps (if enabled)
    if do_ml:
        ok = pip_install(ml_python, ml_reqs, args.dry_run)
        if not ok:
            print("  警告: ML 依赖安装失败,继续后续步骤", file=sys.stderr)

    print("\n[5] 系统依赖 (poppler)")
    install_system_deps(script_dir, args.dry_run)

    print("\n[6] 验证")
    verify(skill_dir, runtime_python)
    print(f"\n安装完成! 用法:")
    print(f"  {runtime_python} {skill_dir}/scripts/extract_pdf_figures.py paper.pdf --mode auto --out ./out")
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_install.py -k "verify_uses_specified or verify_defaults" -v
pytest tests/ -q -k "not real_doclayout"
```
Expected: 2 new tests pass; full suite 174 (was 172; +2). Existing `test_verify_runs_check_deps` still passes (uses default python=None).

- [ ] **Step 5: Smoke test --dry-run**

```bash
cd /home/imalne/learn_vibe_coding
bash .claude/skills/paper-pdf-figures/scripts/install.sh --yes --dry-run
```
Expected: exit 0, prints the new flow (basic+ML to runtime_python).

- [ ] **Step 6: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/scripts/install.py .claude/skills/paper-pdf-figures/tests/test_install.py
git commit -m "fix(paper-pdf-figures): verify uses runtime Python; basic deps follow ML env"
```

---

## Self-Review Notes

**Spec coverage:**
- Problem A (basic deps to ML env) -> `main()` threads `runtime_python`.
- Problem B (verify wrong Python) -> `verify(python)` param.
- Problem C (CPU vs CUDA) -> not in scope (pip upgrade is user's choice); documented as limitation.

**Backward compat:** `verify(skill_dir)` without `python` kwarg defaults to `sys.executable` (existing callers unaffected). `pip_install` unchanged. All existing 172 tests pass.

**Type consistency:** `verify(skill_dir: Path, python: Path = None) -> int`. `main()` passes `runtime_python` (Path). `ml_python` (Path or None). `runtime_python` is always a Path.
