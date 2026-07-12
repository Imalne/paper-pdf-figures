import check_deps


def test_check_py_module_present():
    assert check_deps.check_py_module("os") is True


def test_check_py_module_absent():
    assert check_deps.check_py_module("nope_not_a_module_xyz") is False


def test_check_binary_present():
    assert check_deps.check_binary("python3", which_fn=lambda n: f"/usr/bin/{n}") is True


def test_check_binary_absent():
    assert check_deps.check_binary("nope", which_fn=lambda n: None) is False


def _status_with(present_map):
    """Build a status dict; present_map maps display name -> bool (default True)."""
    status = {}
    for _imp, display, modes, pkg, optional in check_deps.PY_DEPS:
        status[display] = {
            "present": present_map.get(display, True),
            "modes": set(modes), "kind": "python", "install": pkg, "optional": optional,
        }
    for _name, display, optional, pkg, note in check_deps.BIN_DEPS:
        status[display] = {
            "present": present_map.get(display, True),
            "modes": set(), "kind": "binary", "install": pkg,
            "optional": optional, "note": note,
        }
    return status


def test_unavailable_modes_all_present():
    assert check_deps.unavailable_modes(_status_with({})) == []


def test_opencv_missing_blocks_detect_and_auto():
    unavail = set(check_deps.unavailable_modes(_status_with({"opencv-python": False})))
    assert {"detect", "auto"} <= unavail


def test_optional_binary_missing_does_not_block_modes():
    assert check_deps.unavailable_modes(_status_with({"pdftocairo": False})) == []


def test_has_required_missing():
    assert check_deps.has_required_missing(_status_with({"PyMuPDF": False})) is True
    assert check_deps.has_required_missing(_status_with({})) is False


def test_format_report_mentions_missing_and_note():
    report = check_deps.format_report(_status_with({"PyMuPDF": False, "pdftocairo": False}))
    assert "[MISSING] PyMuPDF" in report
    assert "[WARN] pdftocairo" in report
    assert "SVG export unavailable" in report


def test_main_returns_1_when_required_missing(monkeypatch):
    monkeypatch.setattr(check_deps, "collect_status", lambda: _status_with({"PyMuPDF": False}))
    assert check_deps.main() == 1


def test_main_returns_0_when_all_present(monkeypatch):
    monkeypatch.setattr(check_deps, "collect_status", lambda: _status_with({}))
    assert check_deps.main() == 0
