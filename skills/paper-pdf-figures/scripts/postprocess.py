"""Post-processing for auto-mode table crops (Phase 5.2).

- classify_table_or_algorithm: distinguish real tables from algorithm
  pseudocode blocks (DocLayout-YOLO has no `algorithm` class).
- rescan_table_caption: recover table captions the model misclassified as
  plain text / title (text starting with "Table N:").
"""
from __future__ import annotations

import re

from model_detect import LayoutRegion, _center, _union

ALGORITHM_KEYWORDS = [
    "Input:", "Output:", "Require:", "for ", "while ", "return ", "do:",
    "end for", "end while",
]

# Keywords checked line-anchored (line starts with these) to avoid matching
# ordinary English prose ("for all", "while 1,000").
_LINE_ANCHORED_KEYWORDS = ["for ", "while ", "return ", "end for", "end while", "do:"]

_CAPTION_RE = re.compile(r"^Table\s+\d+", re.IGNORECASE)


def classify_table_or_algorithm(text: str) -> str:
    """Return 'algorithm' if `text` looks like pseudocode, else 'table'.

    Heuristics (tightened to avoid misclassifying tables whose captions/body
    contain English words like "for"/"while"):
    1. Table priority: first non-empty line starting with "Table N" -> table.
    2. Strong algorithm signals (anywhere): "Algorithm N", "Algorithm:",
       "Input:" + "Output:" (both), or "Require:".
    3. Line-anchored pseudocode: >=2 lines starting with a pseudocode keyword.
    """
    if not text:
        return "table"
    # 1. Table priority: a "Table N:" caption marks it as a table regardless.
    first_line = next((ln.strip() for ln in text.split("\n") if ln.strip()), "")
    if _CAPTION_RE.match(first_line):
        return "table"
    # 2. Strong signals.
    if re.search(r"Algorithm\s+\d+", text, re.IGNORECASE):
        return "algorithm"
    if re.search(r"Algorithm\s*:", text, re.IGNORECASE):
        return "algorithm"
    if "Input:" in text and "Output:" in text:
        return "algorithm"
    if "Require:" in text:
        return "algorithm"
    # 3. Line-anchored pseudocode keywords (>=2 distinct lines).
    kw_lines = sum(
        1 for ln in text.split("\n")
        if ln.strip() and any(ln.strip().startswith(k) for k in _LINE_ANCHORED_KEYWORDS)
    )
    if kw_lines >= 2:
        return "algorithm"
    return "table"


def rescan_table_caption(
    table_region: LayoutRegion,
    regions: list[LayoutRegion],
    page_num: int,
    text_of,
) -> tuple[LayoutRegion, str]:
    """Find a 'Table N:' caption misclassified as plain text/title; merge bbox.

    `text_of(region) -> str` extracts text from a candidate region (the caller
    knows how to render the page region to text). Returns (merged_region,
    caption_source) where caption_source is 'text-rescan' if found else 'none'.
    """
    candidates = [r for r in regions
                  if r.label in ("plain text", "title") and r is not table_region]
    tcx, tcy = _center(table_region.bbox_pdf_points)
    best, best_d = None, float("inf")
    for r in candidates:
        text = text_of(r)
        first_line = text.strip().split("\n", 1)[0] if text else ""
        if not _CAPTION_RE.match(first_line):
            continue
        rcx, rcy = _center(r.bbox_pdf_points)
        d = abs(rcy - tcy) + abs(rcx - tcx) * 0.1
        if d < best_d:
            best_d, best = d, r
    if best is not None:
        merged = LayoutRegion(
            _union(table_region.bbox_pdf_points, best.bbox_pdf_points),
            table_region.label, table_region.confidence,
        )
        return merged, "text-rescan"
    return table_region, "none"


def _infer_body_in_direction(
    caption_bbox: list[float],
    blocks: list[tuple[float, float, float, float]],
    direction: str,
    page_rect,
) -> list[float] | None:
    """Collect contiguous blocks in `direction` ('up'|'down') from the caption.

    Returns the union bbox of the caption + contiguous body blocks, or None
    if no body found. Stops at a vertical gap > 40pt or the page margin.
    """
    GAP_THRESHOLD = 40.0
    cap_x0, cap_y0, cap_x1, cap_y1 = caption_bbox
    # candidate blocks: horizontally overlap with caption, on the chosen side
    if direction == "down":
        candidates = [b for b in blocks if b[1] >= cap_y1 - 1
                      and b[0] < cap_x1 and b[2] > cap_x0]
        candidates.sort(key=lambda b: b[1])
    else:  # up
        candidates = [b for b in blocks if b[3] <= cap_y0 + 1
                      and b[0] < cap_x1 and b[2] > cap_x0]
        candidates.sort(key=lambda b: -b[3])

    if not candidates:
        return None
    # collect contiguous blocks (gap < threshold between consecutive)
    kept = []
    prev_edge = cap_y1 if direction == "down" else cap_y0
    for b in candidates:
        if direction == "down":
            gap = b[1] - prev_edge
        else:
            gap = prev_edge - b[3]
        if gap > GAP_THRESHOLD:
            break
        kept.append(b)
        prev_edge = b[3] if direction == "down" else b[1]
    if not kept:
        return None
    # union of caption + kept blocks
    x0 = min(cap_x0, *(b[0] for b in kept))
    y0 = min(cap_y0, *(b[1] for b in kept))
    x1 = max(cap_x1, *(b[2] for b in kept))
    y1 = max(cap_y1, *(b[3] for b in kept))
    return [x0, y0, x1, y1]


def caption_driven_fallback(orphan_captions, regions, page) -> list:
    """For each orphan table_caption, infer the table body and return a
    synthetic table LayoutRegion (caption + inferred body union)."""
    page_rect = page.rect
    # raw text blocks from the page (x0,y0,x1,y1,text,block_no,block_type)
    raw_blocks = page.get_text("blocks")
    blocks = [(b[0], b[1], b[2], b[3]) for b in raw_blocks if b[6] == 0]  # text only

    result: list = []
    for cap in orphan_captions:
        down = _infer_body_in_direction(cap.bbox_pdf_points, blocks, "down", page_rect)
        up = _infer_body_in_direction(cap.bbox_pdf_points, blocks, "up", page_rect)
        # pick the direction with more body area
        def area(b):
            return (b[2] - b[0]) * (b[3] - b[1]) if b else 0
        chosen = down if area(down) >= area(up) else up
        if chosen is None:
            continue
        result.append(LayoutRegion(
            bbox_pdf_points=chosen,
            label="table",
            confidence=cap.confidence,
        ))
    return result
