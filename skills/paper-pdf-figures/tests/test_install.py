from pathlib import Path

import install


def test_find_package_explicit(tmp_path):
    pkg = tmp_path / "x.skill"
    pkg.write_bytes(b"PK")  # not a real zip, just a file
    assert install.find_package(str(pkg), tmp_path) == pkg


def test_find_package_default_single_match(tmp_path):
    # mirror real repo layout: <repo>/dist + <repo>/.claude/skills/paper-pdf-figures/scripts
    dist = tmp_path / "dist"
    dist.mkdir()
    pkg = dist / "paper-pdf-figures-0.1.0.skill"
    pkg.write_bytes(b"PK")
    # scripts 4 levels deep so <script_dir>/../../../../dist = tmp_path/dist
    scripts = tmp_path / "skills" / "paper-pdf-figures" / "scripts"
    scripts.mkdir(parents=True)
    assert install.find_package(None, scripts) == pkg


def test_find_package_none_raises(tmp_path):
    # real-depth layout, no dist with packages
    scripts = tmp_path / "skills" / "paper-pdf-figures" / "scripts"
    scripts.mkdir(parents=True)
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
    scripts = tmp_path / "skills" / "paper-pdf-figures" / "scripts"
    scripts.mkdir(parents=True)
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


def test_detect_python_envs_active_marker_skipped(monkeypatch):
    """conda env list active (*) marker must not be parsed as the path."""
    conda_out = (
        "# conda environments:\n"
        "#\n"
        "# * -> active\n"
        "base                 *   /home/u/anaconda3\n"
        "myenv                    /home/u/.conda/envs/myenv\n"
    )
    import subprocess
    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, conda_out, "")
    monkeypatch.setattr(install.subprocess, "run", fake_run)
    monkeypatch.setattr(install.shutil, "which", lambda n: "/usr/bin/conda")
    envs = install.detect_python_envs()
    # find the conda:base env
    base_env = [e for e in envs if "base" in e.name][0]
    # python path must be the real path, not */bin/python
    assert str(base_env.python) == "/home/u/anaconda3/bin/python", \
        f"expected /home/u/anaconda3/bin/python, got {base_env.python}"


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


def test_main_basic_deps_follow_ml_env(tmp_path, monkeypatch):
    """When --ml --ml-env points to a different python, basic+ML deps + verify
    all use that python (not sys.executable)."""
    import zipfile
    repo = tmp_path
    dist = repo / "dist"
    dist.mkdir()
    pkg = dist / "paper-pdf-figures-0.1.0.skill"
    with zipfile.ZipFile(pkg, "w") as z:
        z.writestr("paper-pdf-figures/SKILL.md", "x")
        z.writestr("paper-pdf-figures/VERSION", "0.1.0")
        z.writestr("paper-pdf-figures/requirements.txt", "pymupdf")
        z.writestr("paper-pdf-figures/requirements-ml.txt", "torch")
        z.writestr("paper-pdf-figures/scripts/check_deps.py", "print('[OK]')")
    scripts = repo / ".claude" / "skills" / "paper-pdf-figures" / "scripts"
    scripts.mkdir(parents=True)
    import shutil as _sh
    _sh.copy(str(Path(__file__).resolve().parent.parent / "scripts" / "install.py"),
             str(scripts / "install.py"))

    pip_pythons = []
    verify_pythons = []
    import install as _inst

    def spy_pip(python, reqs_file, dry_run):
        pip_pythons.append(str(python))
        return True
    def spy_verify(skill_dir, python=None):
        verify_pythons.append(str(python) if python else "default")
        return 0
    monkeypatch.setattr(_inst, "pip_install", spy_pip)
    monkeypatch.setattr(_inst, "verify", spy_verify)
    monkeypatch.setattr(_inst, "install_system_deps", lambda *a, **kw: None)

    ml_python = "/fake/venv/bin/python3"
    target = tmp_path / "target"
    rc = _inst.main(["--yes", "--ml", "--ml-env", ml_python,
                     "--target", str(target), "--package", str(pkg)])
    assert rc == 0
    # basic deps -> ml_python (runtime_python), ML deps -> ml_python
    assert len(pip_pythons) == 2
    assert pip_pythons[0] == ml_python  # basic deps followed ML env
    assert pip_pythons[1] == ml_python  # ML deps
    # verify also used the ML env python
    assert verify_pythons[0] == ml_python


def test_generate_run_sh(tmp_path):
    """run.sh is generated with the correct python and is executable."""
    skill = tmp_path / "paper-pdf-figures"
    (skill / "scripts").mkdir(parents=True)
    install.generate_run_sh(skill, Path("/fake/venv/bin/python3"))
    run_sh = skill / "scripts" / "run.sh"
    assert run_sh.is_file()
    import os, stat
    mode = run_sh.stat().st_mode
    assert mode & stat.S_IXUSR, "run.sh should be executable"
    content = run_sh.read_text()
    assert "/fake/venv/bin/python3" in content
    assert "extract_pdf_figures.py" in content


def test_patch_skill_md(tmp_path):
    """SKILL.md is patched to use run.sh instead of python3."""
    skill = tmp_path / "paper-pdf-figures"
    skill.mkdir()
    md = skill / "SKILL.md"
    md.write_text(
        "```bash\n"
        'python3 ${CLAUDE_SKILL_DIR}/scripts/extract_pdf_figures.py "$ARGUMENTS"\n'
        "```\n"
    )
    install.patch_skill_md(skill)
    patched = md.read_text()
    assert 'bash ${CLAUDE_SKILL_DIR}/scripts/run.sh "$ARGUMENTS"' in patched
    assert "python3 ${CLAUDE_SKILL_DIR}/scripts/extract_pdf_figures.py" not in patched


def test_patch_skill_md_idempotent(tmp_path):
    """Patching an already-patched SKILL.md is a no-op."""
    skill = tmp_path / "paper-pdf-figures"
    skill.mkdir()
    md = skill / "SKILL.md"
    md.write_text('bash ${CLAUDE_SKILL_DIR}/scripts/run.sh "$ARGUMENTS"\n')
    install.patch_skill_md(skill)
    assert "run.sh" in md.read_text()


def test_ask_hf_endpoint_not_ml():
    """When ML not installed, returns None (no endpoint needed)."""
    assert install.ask_hf_endpoint(do_ml=False, non_interactive=False) is None


def test_ask_hf_endpoint_non_interactive():
    """Non-interactive defaults to None (direct huggingface.co)."""
    assert install.ask_hf_endpoint(do_ml=True, non_interactive=True) is None


def test_ask_hf_endpoint_mirror(monkeypatch):
    """Interactive: user picks option 2 -> hf-mirror.com."""
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("2\n"))
    assert install.ask_hf_endpoint(do_ml=True, non_interactive=False) == "https://hf-mirror.com"


def test_ask_hf_endpoint_custom(monkeypatch):
    """Interactive: user picks 3 and enters a custom URL."""
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("3\nhttps://my.mirror.com\n"))
    assert install.ask_hf_endpoint(do_ml=True, non_interactive=False) == "https://my.mirror.com"


def test_generate_run_sh_with_endpoint(tmp_path):
    """run.sh includes HF_ENDPOINT export when endpoint is set."""
    skill = tmp_path / "paper-pdf-figures"
    (skill / "scripts").mkdir(parents=True)
    install.generate_run_sh(skill, Path("/usr/bin/python3"),
                             hf_endpoint="https://hf-mirror.com")
    content = (skill / "scripts" / "run.sh").read_text()
    assert "export HF_ENDPOINT=https://hf-mirror.com" in content


def test_generate_run_sh_no_endpoint(tmp_path):
    """run.sh has no HF_ENDPOINT export when endpoint is None."""
    skill = tmp_path / "paper-pdf-figures"
    (skill / "scripts").mkdir(parents=True)
    install.generate_run_sh(skill, Path("/usr/bin/python3"), hf_endpoint=None)
    content = (skill / "scripts" / "run.sh").read_text()
    assert "HF_ENDPOINT" not in content


def test_in_place_install_no_package_needed(monkeypatch):
    """When install.py runs from inside an extracted skill dir (has SKILL.md +
    VERSION), it skips find_package + extract and installs in-place (no
    FileNotFoundError for missing .skill package)."""
    import install
    monkeypatch.setattr(install, "pip_install", lambda *a, **kw: True)
    monkeypatch.setattr(install, "verify", lambda *a, **kw: 0)
    monkeypatch.setattr(install, "install_system_deps", lambda *a, **kw: None)
    monkeypatch.setattr(install, "generate_run_sh", lambda *a, **kw: None)
    monkeypatch.setattr(install, "patch_skill_md", lambda *a, **kw: None)
    # The real install.py runs from the actual skill dir which HAS SKILL.md +
    # VERSION, so in_place=True. With --no-ml and no --package, it should skip
    # find_package and succeed without FileNotFoundError.
    rc = install.main(["--yes", "--no-ml"])
    assert rc == 0


def test_ask_skill_language_non_interactive():
    assert install.ask_skill_language(non_interactive=True) == "en"


def test_ask_skill_language_zh(monkeypatch):
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("2\n"))
    assert install.ask_skill_language(non_interactive=False) == "zh"


def test_ask_skill_language_en(monkeypatch):
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("1\n"))
    assert install.ask_skill_language(non_interactive=False) == "en"


def test_switch_skill_language_zh(tmp_path):
    """Switch to ZH: SKILL.md becomes Chinese, EN saved as SKILL_EN.md."""
    skill = tmp_path / "paper-pdf-figures"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# English skill")
    (skill / "SKILL_ZH.md").write_text("# 中文技能")
    install.switch_skill_language(skill, "zh")
    assert (skill / "SKILL.md").read_text() == "# 中文技能"
    assert (skill / "SKILL_EN.md").read_text() == "# English skill"
    assert not (skill / "SKILL_ZH.md").exists()


def test_switch_skill_language_en_noop(tmp_path):
    """Switch to EN (default): no change."""
    skill = tmp_path / "paper-pdf-figures"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# English skill")
    (skill / "SKILL_ZH.md").write_text("# 中文技能")
    install.switch_skill_language(skill, "en")
    assert (skill / "SKILL.md").read_text() == "# English skill"
    assert (skill / "SKILL_ZH.md").read_text() == "# 中文技能"


def test_switch_skill_language_zh_then_back_en(tmp_path):
    """Switch ZH -> EN -> ZH round-trip."""
    skill = tmp_path / "paper-pdf-figures"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# English skill")
    (skill / "SKILL_ZH.md").write_text("# 中文技能")
    # Switch to ZH
    install.switch_skill_language(skill, "zh")
    assert (skill / "SKILL.md").read_text() == "# 中文技能"
    assert (skill / "SKILL_EN.md").read_text() == "# English skill"
    # Switch back to EN
    install.switch_skill_language(skill, "en")
    assert (skill / "SKILL.md").read_text() == "# English skill"
    assert (skill / "SKILL_ZH.md").read_text() == "# 中文技能"
