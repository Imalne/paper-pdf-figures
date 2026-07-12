#!/usr/bin/env python3
"""Check dependencies for paper-pdf-figures and report per-mode availability."""
from __future__ import annotations

import importlib
import shutil
import sys

# (import_name, display, modes_blocked_if_missing, install_pkg, optional)
# `optional=True` means a missing dep -> WARN (not MISSING) and does not drive
# the exit code; it still lists its `modes` as unavailable when missing.
PY_DEPS = [
    ("fitz", "PyMuPDF", {"embedded", "manual", "render", "auto"}, "pymupdf", False),
    ("PIL", "Pillow", {"embedded", "manual", "render", "auto"}, "pillow", False),
    ("yaml", "PyYAML", {"manual", "auto"}, "pyyaml", False),
    ("numpy", "numpy", {"detect", "auto"}, "numpy", False),
    ("cv2", "opencv-python", {"detect", "auto"}, "opencv-python", False),
    ("torch", "torch", {"auto"}, "torch", True),
    ("doclayout_yolo", "doclayout-yolo", {"auto"}, "doclayout-yolo", True),
]

# (binary, display, optional, install_pkg, note_if_missing)
BIN_DEPS = [
    ("pdftocairo", "pdftocairo", True, "poppler-utils",
     "SVG export unavailable (PDF+PNG still work)."),
    ("pdfimages", "pdfimages", True, "poppler-utils",
     "Embedded-image cross-check unavailable (PyMuPDF extraction still works)."),
    ("mutool", "mutool", True, "mupdf-tools",
     "Fallback extraction unavailable (not used in MVP)."),
]

ALL_MODES = {"embedded", "manual", "detect", "render", "auto"}


def check_py_module(import_name: str, importer=importlib.import_module) -> bool:
    try:
        importer(import_name)
        return True
    except ImportError:
        return False


def check_binary(name: str, which_fn=shutil.which) -> bool:
    return which_fn(name) is not None


def collect_status(which_fn=shutil.which, module_checker=check_py_module) -> dict:
    status = {}
    for imp, display, modes, pkg, optional in PY_DEPS:
        status[display] = {
            "present": module_checker(imp),
            "modes": set(modes),
            "kind": "python",
            "install": pkg,
            "optional": optional,
        }
    for name, display, optional, pkg, note in BIN_DEPS:
        status[display] = {
            "present": check_binary(name, which_fn),
            "modes": set(),
            "kind": "binary",
            "install": pkg,
            "optional": optional,
            "note": note,
        }
    return status


def unavailable_modes(status: dict) -> list[str]:
    blocked: set[str] = set()
    for info in status.values():
        if not info["present"] and info["modes"]:
            blocked |= info["modes"]
    return sorted(blocked)


def has_required_missing(status: dict) -> bool:
    return any(
        not info["present"] and info["modes"] and not info["optional"]
        for info in status.values()
    )


def format_report(status: dict) -> str:
    lines = []
    py_ok = sys.version_info >= (3, 9)
    py_ver = ".".join(map(str, sys.version_info[:3]))
    lines.append(f"[{'OK' if py_ok else 'FAIL'}] Python {py_ver} (>=3.9 required)")
    for display, info in status.items():
        if info["present"]:
            mark = "OK"
        elif info["optional"]:
            mark = "WARN"
        else:
            mark = "MISSING"
        lines.append(f"[{mark}] {display}")
    unavailable = unavailable_modes(status)
    if unavailable:
        lines.append(f"Unavailable modes (missing required deps): {', '.join(unavailable)}")
    else:
        lines.append("All modes available.")
    for display, info in status.items():
        if not info["present"] and info["kind"] == "binary":
            lines.append(f"Note: {display} missing — {info['note']}")
    return "\n".join(lines)


def main() -> int:
    status = collect_status()
    print(format_report(status))
    return 1 if has_required_missing(status) else 0


if __name__ == "__main__":
    sys.exit(main())
