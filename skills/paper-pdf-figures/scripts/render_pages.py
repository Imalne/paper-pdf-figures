"""Render PDF pages/regions to PNG + contact sheet (--mode render)."""
from __future__ import annotations

from pathlib import Path

import fitz
from PIL import Image

from crop_export import FigureConfig
from manifest import RenderedItem


def render_pages(
    doc: "fitz.Document",
    pages: set[int] | None,
    out_dir: Path | str,
    slug: str,
    dpi: int = 300,
    dry_run: bool = False,
) -> list[RenderedItem]:
    """Render whole pages to pages/p{page:04d}.png."""
    out_dir = Path(out_dir)
    pages_dir = out_dir / slug / "pages"
    if not dry_run:
        pages_dir.mkdir(parents=True, exist_ok=True)
    if pages is None:
        page_indices = range(len(doc))
    else:
        page_indices = sorted(p - 1 for p in pages if 1 <= p <= len(doc))
    items: list[RenderedItem] = []
    for pno in page_indices:
        pix = doc[pno].get_pixmap(dpi=dpi)
        page_1 = pno + 1
        rel = f"pages/p{page_1:04d}.png"
        if not dry_run:
            pix.save(str(pages_dir / f"p{page_1:04d}.png"))
        items.append(RenderedItem(
            id=f"page_{page_1:04d}", page=page_1, file=rel,
            dpi=dpi, width=pix.width, height=pix.height,
        ))
    return items


def render_regions(
    doc: "fitz.Document",
    figures: list[FigureConfig],
    out_dir: Path | str,
    slug: str,
    dpi: int = 300,
    dry_run: bool = False,
) -> list[RenderedItem]:
    """Render bbox regions to regions/{id}.png."""
    out_dir = Path(out_dir)
    regions_dir = out_dir / slug / "regions"
    if not dry_run:
        regions_dir.mkdir(parents=True, exist_ok=True)
    items: list[RenderedItem] = []
    for fig in figures:
        if fig.page < 1 or fig.page > len(doc):
            continue
        clip = fitz.Rect(*fig.bbox)
        if clip.is_empty or clip.width <= 0 or clip.height <= 0:
            continue  # skip zero-area / inverted bbox (degenerate)
        pix = doc[fig.page - 1].get_pixmap(dpi=dpi, clip=clip)
        rel = f"regions/{fig.id}.png"
        if not dry_run:
            pix.save(str(regions_dir / f"{fig.id}.png"))
        items.append(RenderedItem(
            id=fig.id, page=fig.page, file=rel,
            dpi=dpi, width=pix.width, height=pix.height,
        ))
    return items


def make_contact_sheet(
    items: list[RenderedItem],
    out_dir: Path | str,
    slug: str,
    dry_run: bool = False,
    cols: int = 4,
    thumb_w: int = 300,
) -> Path | None:
    """Compose all rendered PNGs into summary_contact_sheet.png."""
    if not items:
        return None
    out_dir = Path(out_dir)
    sheet_path = out_dir / slug / "summary_contact_sheet.png"
    if dry_run:
        return None
    thumbs = []
    for it in items:
        img_path = out_dir / slug / it.file
        if not img_path.is_file():
            continue
        im = Image.open(img_path)
        ratio = thumb_w / im.width
        im = im.resize((thumb_w, max(1, int(im.height * ratio))))
        thumbs.append((it, im))
    if not thumbs:
        return None
    rows = (len(thumbs) + cols - 1) // cols
    thumb_h = max(im.height for _, im in thumbs)
    label_h = 20
    cell_h = thumb_h + label_h
    sheet = Image.new("RGB", (cols * thumb_w, rows * cell_h), "white")
    from PIL import ImageDraw
    draw = ImageDraw.Draw(sheet)
    for idx, (it, im) in enumerate(thumbs):
        r, c = divmod(idx, cols)
        x = c * thumb_w
        y = r * cell_h
        sheet.paste(im, (x, y))
        draw.text((x + 2, y + thumb_h + 2), f"p{it.page} {it.id}", fill="black")
    sheet.save(str(sheet_path))
    return sheet_path
