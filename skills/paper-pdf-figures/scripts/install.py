#!/usr/bin/env python3
"""One-click installer for the paper-pdf-figures skill (.skill -> Claude Code)."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path


def find_package(package_arg: str | None, script_dir: Path) -> Path:
    """Locate the .skill zip to install.

    package_arg if given (explicit path); else the single
    paper-pdf-figures-*.skill in <script_dir>/../../../../dist/ (repo-root
    dist/, matching package.sh's 4-levels-up resolution from scripts/).
    Raises FileNotFoundError if none or ambiguous.
    """
    if package_arg:
        p = Path(package_arg)
        if not p.is_file():
            raise FileNotFoundError(f"package not found: {package_arg}")
        return p
    # scripts/ -> paper-pdf-figures/ -> skills/ -> .claude/ -> <repo>/
    dist = script_dir.parent.parent.parent / "dist"
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


@dataclass
class PythonEnv:
    name: str
    python: Path
    kind: str  # "current" | "conda" | "venv"


@dataclass
class DepStatus:
    name: str
    status: str  # "ok" | "warn" | "missing"


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
                # conda env list marks active (*) / frozen (+) envs with a
                # marker between name and path; filter them out so we get
                # [name, path], not [name, '*', path].
                parts = [p for p in parts if p not in ("*", "+")]
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
    # pass valid choices so prompt re-prompts on invalid input (no raw traceback)
    valid = [str(i) for i in range(1, len(envs) + 2)]
    raw = prompt(f"  选择", choices=valid, default=str(default_idx + 1), non_interactive=False)
    idx = int(raw) - 1
    if 0 <= idx < len(envs):
        return envs[idx].python
    # "other" -> ask for a path
    path = prompt("  python 路径", default=None, non_interactive=False)
    return Path(path)


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


def verify(skill_dir: Path, python: Path | None = None) -> int:
    """Run check_deps.py in skill_dir, print a 5-mode summary, return exit code."""
    if python is None:
        python = Path(sys.executable)
    skill_dir = skill_dir.resolve()
    check = skill_dir / "scripts" / "check_deps.py"
    res = subprocess.run([str(python), str(check)], capture_output=True,
                         text=True, check=False, cwd=str(skill_dir))
    deps, unavail = parse_check_deps_output(res.stdout)
    print("  依赖状态:")
    for d in deps:
        mark = {"ok": "[OK]", "warn": "[WARN]", "missing": "[MISSING]"}[d.status]
        print(f"    {mark} {d.name}")
    if not deps:
        print("    (无输出 - check_deps 可能崩溃或缺失)")
        print(f"    stderr: {res.stderr.strip()[:200] or '(空)'}")
    modes = ["embedded", "manual", "detect", "render", "auto"]
    print("  模式可用性:")
    for m in modes:
        if m in unavail:
            print(f"    {m:10s} 不可用 (缺依赖)")
        else:
            print(f"    {m:10s} 可用")
    return res.returncode


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


def pip_install(python: Path, reqs_file: Path, dry_run: bool) -> bool:
    """Run <python> -m pip install -r <reqs>. Returns True on success."""
    if dry_run:
        print(f"  [dry-run] {python} -m pip install -r {reqs_file.name}")
        return True
    print(f"  安装 {reqs_file.name} -> {python}")
    try:
        res = subprocess.run([str(python), "-m", "pip", "install", "-r", str(reqs_file)],
                            capture_output=False, check=False)
    except (FileNotFoundError, OSError) as e:
        print(f"  ERROR: 无法运行 {python}: {e}", file=sys.stderr)
        print(f"    检查 python 路径是否正确", file=sys.stderr)
        return False
    if res.returncode != 0:
        print(f"  ERROR: pip install 失败 ({reqs_file.name})。手动尝试:", file=sys.stderr)
        print(f"    {python} -m pip install -r {reqs_file}", file=sys.stderr)
        return False
    return True


def ask_hf_endpoint(do_ml: bool, non_interactive: bool) -> str | None:
    """Ask which HuggingFace endpoint to use for model weight download.

    Only asked when ML deps are being installed. Returns the URL or None
    (direct huggingface.co). Non-interactive -> None (direct).
    """
    if not do_ml:
        return None
    if non_interactive:
        return None
    print("\n  模型权重下载途径:")
    print("    1) 直连 huggingface.co  <- 默认")
    print("    2) 镜像 hf-mirror.com")
    print("    3) 自定义 URL")
    raw = prompt("  选择", default="1", non_interactive=False)
    if raw == "2":
        return "https://hf-mirror.com"
    if raw == "3":
        url = prompt("  URL", default=None, non_interactive=False)
        return url if url else None
    return None


def generate_run_sh(skill_dir: Path, python: Path,
                    hf_endpoint: str | None = None) -> None:
    """Generate scripts/run.sh wrapper so the skill always runs with the
    installed Python env (not whatever `python3` the calling shell finds).
    If hf_endpoint is set, exports HF_ENDPOINT before running."""
    run_sh = skill_dir / "scripts" / "run.sh"
    lines = [
        "#!/usr/bin/env bash",
        "# Auto-generated by install.py -- points to the Python env with deps.",
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
    ]
    if hf_endpoint:
        lines.append(f'export HF_ENDPOINT={hf_endpoint}')
    lines.append(f'exec {python.resolve()} "$SCRIPT_DIR/extract_pdf_figures.py" "$@"')
    content = "\n".join(lines) + "\n"
    run_sh.write_text(content)
    run_sh.chmod(0o755)
    ep_msg = f" (HF_ENDPOINT={hf_endpoint})" if hf_endpoint else ""
    print(f"  生成 run.sh -> {python}{ep_msg}")


def patch_skill_md(skill_dir: Path) -> None:
    """Patch the extracted SKILL.md to use run.sh instead of python3 for
    extract_pdf_figures.py calls (so Claude Code uses the right Python env)."""
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        return
    text = md.read_text()
    old = 'python3 ${CLAUDE_SKILL_DIR}/scripts/extract_pdf_figures.py "$ARGUMENTS"'
    new = 'bash ${CLAUDE_SKILL_DIR}/scripts/run.sh "$ARGUMENTS"'
    if old in text:
        text = text.replace(old, new)
        md.write_text(text)
        print("  SKILL.md 已更新: 用 run.sh 替代 python3")


def ask_skill_language(non_interactive: bool = False) -> str:
    """Ask which language version should be the active SKILL.md.
    Returns 'en' (default) or 'zh'."""
    if non_interactive:
        return "en"
    print("\n  SKILL.md 语言:")
    print("    1) English (默认)  <- SKILL.md = 英文, 中文存为 SKILL_ZH.md")
    print("    2) 中文            <- SKILL.md = 中文, 英文存为 SKILL_EN.md")
    raw = prompt("  选择", default="1", non_interactive=False)
    return "zh" if raw == "2" else "en"


def switch_skill_language(skill_dir: Path, lang: str) -> None:
    """Switch the active SKILL.md to the chosen language.
    en: SKILL.md=EN, ZH saved as SKILL_ZH.md (default).
    zh: SKILL.md=ZH, EN saved as SKILL_EN.md."""
    en = skill_dir / "SKILL.md"
    zh = skill_dir / "SKILL_ZH.md"
    en_bak = skill_dir / "SKILL_EN.md"

    if lang == "zh":
        if not zh.is_file():
            return  # no ZH to switch to
        if en_bak.is_file():
            return  # already switched (EN backed up, SKILL.md is ZH)
        # EN -> SKILL_EN.md, ZH -> SKILL.md
        en.rename(en_bak)
        zh.rename(en)
        print("  SKILL.md 已切换为中文 (英文存为 SKILL_EN.md)")
    else:
        # lang == "en": restore EN as active if ZH was active
        if not en_bak.is_file():
            return  # already EN (default state)
        # Current SKILL.md (ZH content) -> SKILL_ZH.md
        # SKILL_EN.md -> SKILL.md
        if zh.is_file():
            zh.unlink()
        en.rename(zh)
        en_bak.rename(en)
        print("  SKILL.md 已切换为英文 (中文存为 SKILL_ZH.md)")


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="install", description=__doc__)
    parser.add_argument("--yes", action="store_true", help="non-interactive, use defaults")
    parser.add_argument("--package", default=None)
    parser.add_argument("--target", default=None)
    parser.add_argument("--ml", action="store_true")
    parser.add_argument("--no-ml", action="store_true")
    parser.add_argument("--ml-env", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skill-lang", default=None, choices=["en", "zh"],
                        help="which language for SKILL.md (en default, zh)")
    args = parser.parse_args(argv)

    script_dir = Path(__file__).resolve().parent
    skill_root = script_dir.parent

    print("paper-pdf-figures 安装程序")
    print("=" * 40)

    # Detect in-place mode: if install.py is running from inside an already-
    # extracted skill dir (has SKILL.md + VERSION + requirements.txt), skip
    # find_package + extract and use skill_root directly.
    in_place = (skill_root / "SKILL.md").is_file() and (skill_root / "VERSION").is_file()

    if in_place and not args.package:
        # In-place: install deps + generate run.sh for this skill dir.
        skill_dir = skill_root
        print(f"就地安装模式 (技能目录: {skill_dir})")
    else:
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
        try:
            skill_dir = extract_package(pkg, target, action, args.dry_run)
        except zipfile.BadZipFile as e:
            print(f"ERROR: 包损坏或不是有效的 .skill 文件: {e}", file=sys.stderr)
            return 1
        if args.dry_run:
            print("\n[dry-run] 跳过依赖安装与验证")
            return 0

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

    print("\n[6] 生成运行时 wrapper + 更新 SKILL.md")
    # Language switch (before patch_skill_md so patch applies to active SKILL.md)
    skill_lang = args.skill_lang or ask_skill_language(args.yes)
    switch_skill_language(skill_dir, skill_lang)
    hf_endpoint = ask_hf_endpoint(do_ml, args.yes)
    generate_run_sh(skill_dir, runtime_python, hf_endpoint)
    patch_skill_md(skill_dir)

    print("\n[7] 验证")
    verify(skill_dir, runtime_python)
    print(f"\n安装完成! 用法:")
    print(f"  bash {skill_dir}/scripts/run.sh paper.pdf --mode auto --out ./out")
    return 0


if __name__ == "__main__":
    sys.exit(main())
