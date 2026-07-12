"""Extract embedded raster images from a PDF (Phase 1: --mode embedded)."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

import fitz

from manifest import EmbeddedImage


def extract_embedded_images(
    doc: "fitz.Document",
    out_dir: Path | str,
    paper_slug: str,
    pages: Iterable[int] | None = None,
    dry_run: bool = False,
    warnings: list | None = None,
) -> list[EmbeddedImage]:
    """Extract every unique embedded image xref in `doc`.

    Args:
        doc: open fitz.Document (read-only; not modified).
        out_dir: root output directory; writes to `<out_dir>/<paper_slug>/embedded/`.
        paper_slug: subdirectory name for this paper's outputs.
        pages: iterable of 1-based page numbers to restrict to, or None for all.
        dry_run: if True, return records without writing files.

    Returns:
        One EmbeddedImage per unique xref, in first-seen order. `page` is 1-based
        (first page the xref appears on); `file` is relative to `out_dir`.
    """
    out_dir = Path(out_dir)
    embedded_dir = out_dir / paper_slug / "embedded"
    if not dry_run:
        embedded_dir.mkdir(parents=True, exist_ok=True)

    if pages is None:
        page_indices = range(len(doc))
    else:
        page_indices = sorted(p - 1 for p in pages if 1 <= p <= len(doc))

    seen: set[int] = set()
    results: list[EmbeddedImage] = []

    for pno in page_indices:
        page = doc[pno]
        page_1based = pno + 1
        for img in page.get_images(full=True):
            xref = img[0]
            if xref in seen:
                continue
            seen.add(xref)
            try:
                info = doc.extract_image(xref)
            except Exception as e:
                if warnings is not None:
                    warnings.append(("WARN_EXTRACT_IMAGE_FAILED", page_1based,
                                     f"xref {xref}: {e}"))
                continue
            ext = info.get("ext", "bin")
            image_bytes = info["image"]
            width = int(info.get("width", 0))
            height = int(info.get("height", 0))
            if width < 1 or height < 1:
                if warnings is not None:
                    warnings.append(("WARN_ZERO_DIMENSION_IMAGE", page_1based,
                                     f"xref {xref}: {width}x{height}"))
                continue
            sha = hashlib.sha256(image_bytes).hexdigest()
            rel_path = f"embedded/p{page_1based:04d}_xref{xref:06d}.{ext}"
            if not dry_run:
                (embedded_dir / f"p{page_1based:04d}_xref{xref:06d}.{ext}").write_bytes(image_bytes)
            results.append(EmbeddedImage(
                id=f"embedded_p{page_1based:04d}_xref{xref:06d}",
                page=page_1based,
                xref=xref,
                format=ext,
                width=width,
                height=height,
                file=rel_path,
                sha256=sha,
            ))
    return results
