import postprocess
import model_detect


def _region(label, bbox, conf=0.9):
    return model_detect.LayoutRegion(bbox_pdf_points=list(bbox), label=label, confidence=conf)


def test_classify_algorithm_N():
    assert postprocess.classify_table_or_algorithm(
        "Algorithm 4 Momentum MDM-VGB sampler") == "algorithm"


def test_classify_algorithm_colon():
    assert postprocess.classify_table_or_algorithm(
        "Algorithm: do stuff") == "algorithm"


def test_classify_pseudocode_keywords():
    text = "Input: context x\nOutput: result\nfor x in y: do something"
    assert postprocess.classify_table_or_algorithm(text) == "algorithm"


def test_classify_single_keyword_is_table():
    # only one pseudocode keyword -> not enough -> table
    text = "Method Letter Acc. Input: foo"
    assert postprocess.classify_table_or_algorithm(text) == "table"


def test_classify_real_table_is_table():
    text = "Heuristic verifier Learned verifier Method Letter Sudoku QM9\n25.6 30.1"
    assert postprocess.classify_table_or_algorithm(text) == "table"


def test_classify_empty_text_is_table():
    assert postprocess.classify_table_or_algorithm("") == "table"


def test_rescan_finds_table_caption_in_plain_text():
    # table at [100,200,400,300]; caption "Table 1:..." misdetected as plain text below at [100,310,400,340]
    tbl = _region("table", [100, 200, 400, 300])
    caption = _region("plain text", [100, 310, 400, 340])
    # simulate text starting with "Table 1:"
    import fitz
    # rescan works on regions; we need the text. For unit test, patch the text getter.
    # Easier: rescan takes a text-extractor callable.
    def text_of(region):
        if region is caption:
            return "Table 1: Generation results."
        return "some other text"
    merged, source = postprocess.rescan_table_caption(
        tbl, [caption, _region("plain text", [100, 400, 400, 450])],
        page_num=11, text_of=text_of,
    )
    assert source == "text-rescan"
    assert merged.bbox_pdf_points == [100, 200, 400, 340]  # union


def test_rescan_returns_none_when_no_caption():
    tbl = _region("table", [100, 200, 400, 300])
    other = _region("plain text", [100, 400, 400, 450])
    def text_of(region):
        return "just body text, no Table N:"
    merged, source = postprocess.rescan_table_caption(tbl, [other], page_num=11, text_of=text_of)
    assert source == "none"
    assert merged.bbox_pdf_points == [100, 200, 400, 300]  # unchanged


def test_rescan_picks_nearest_caption():
    tbl = _region("table", [100, 200, 400, 300])
    near = _region("plain text", [100, 310, 400, 340])
    far = _region("title", [100, 600, 400, 630])
    def text_of(region):
        if region is near: return "Table 1: near."
        if region is far: return "Table 99: far."
        return "body"
    merged, source = postprocess.rescan_table_caption(
        tbl, [far, near], page_num=11, text_of=text_of)
    assert source == "text-rescan"
    # near is closer (gap 10) than far (gap 300)
    assert merged.bbox_pdf_points == [100, 200, 400, 340]


def test_caption_driven_fallback_picks_below_dense_blocks():
    """Caption at top; table body (dense blocks) below -> bbox extends down."""
    import fitz
    # build a page: caption "Table 1:" at y=100-130; table body blocks at y=150-300
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((135, 120), "Table 1: Some caption.", fontsize=10)
    for i in range(6):
        page.insert_text((135, 160 + i * 25), "row data col1 col2 col3", fontsize=9)
    cap = _region("table_caption", [130, 105, 480, 130])
    result = postprocess.caption_driven_fallback([cap], [], page)
    assert len(result) == 1
    bbox = result[0].bbox_pdf_points
    # bbox should extend below the caption into the body
    assert bbox[3] > 200  # y1 reaches into body
    assert bbox[1] <= 105  # y0 starts at caption top
    assert result[0].label == "table"
    doc.close()


def test_caption_driven_fallback_picks_above_when_dense_above():
    """Caption at bottom; table body above -> bbox extends up."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    # body above caption (within 40pt gap threshold of the caption region)
    for i in range(6):
        page.insert_text((135, 225 + i * 25), "row data col1 col2", fontsize=9)
    page.insert_text((135, 400), "Table 2: caption below table.", fontsize=10)
    cap = _region("table_caption", [130, 385, 480, 410])
    result = postprocess.caption_driven_fallback([cap], [], page)
    assert len(result) == 1
    bbox = result[0].bbox_pdf_points
    assert bbox[1] < 250  # y0 reaches up into body
    assert bbox[3] >= 385  # y1 includes caption
    doc.close()


def test_caption_driven_fallback_skips_when_no_adjacent_blocks():
    """Orphan caption with no nearby text blocks -> skip (return empty)."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((135, 120), "Table 1: orphan caption alone.", fontsize=10)
    cap = _region("table_caption", [130, 105, 480, 130])
    result = postprocess.caption_driven_fallback([cap], [], page)
    assert result == []  # nothing to infer a body from


def test_caption_driven_fallback_stops_at_large_gap():
    """Body blocks then a large gap then unrelated text -> bbox stops at the gap."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((135, 120), "Table 1: cap.", fontsize=10)
    # contiguous body y=150-250
    for i in range(4):
        page.insert_text((135, 150 + i * 25), "row col1 col2", fontsize=9)
    # big gap, then unrelated text at y=600
    page.insert_text((135, 600), "Unrelated paragraph far below.", fontsize=10)
    cap = _region("table_caption", [130, 105, 480, 130])
    result = postprocess.caption_driven_fallback([cap], [], page)
    assert len(result) == 1
    bbox = result[0].bbox_pdf_points
    assert bbox[3] < 300  # y1 stops before the gap (not reaching 600)
    doc.close()


def test_caption_driven_fallback_union_with_caption():
    """Result bbox is the union of caption + inferred body."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((135, 120), "Table 1: cap.", fontsize=10)
    for i in range(3):
        page.insert_text((135, 160 + i * 25), "row col1 col2", fontsize=9)
    cap = _region("table_caption", [130, 105, 480, 130])
    result = postprocess.caption_driven_fallback([cap], [], page)
    bbox = result[0].bbox_pdf_points
    # union: x covers caption+body, y from caption top to last body block
    assert bbox[0] <= 130 and bbox[2] >= 480  # x span covers caption width
    doc.close()


# ===== Phase 5.2 fix: tightened classify_table_or_algorithm =====

def test_classify_table_caption_priority_over_keywords():
    """A 'Table N:' first line -> table, even if body has 'for'/'while' words."""
    text = ("Table 3: Quantitative comparison on VBench; higher is better for all "
            "metrics. Shell-LCC reduces distortion. while 1,000 videos already reach.")
    assert postprocess.classify_table_or_algorithm(text) == "table"


def test_classify_english_prose_not_algorithm():
    """Body text with 'for'/'while' as English words (not line-anchored) -> table."""
    text = ("Here µDev and σDev are computed from base-model calibration samples. "
            "for data distribution. while 1,000 videos reach accuracy.")
    assert postprocess.classify_table_or_algorithm(text) == "table"


def test_classify_require_is_algorithm():
    """Require: (algorithm convention) -> algorithm."""
    assert postprocess.classify_table_or_algorithm(
        "Require: context x, initial masked state z0, reference model πref"
    ) == "algorithm"


def test_classify_line_anchored_pseudocode():
    """Pseudocode keywords at line start (>=2 lines) -> algorithm."""
    text = "for each i in U do\n    extract z_i\nreturn z"
    assert postprocess.classify_table_or_algorithm(text) == "algorithm"


def test_classify_input_output_both_present():
    """Input: AND Output: both present -> algorithm (strong signal)."""
    assert postprocess.classify_table_or_algorithm(
        "Input: image set D\nOutput: token rank π"
    ) == "algorithm"


def test_classify_input_only_is_table():
    """Only Input: (no Output:) and no other signal -> table (single kw insufficient)."""
    assert postprocess.classify_table_or_algorithm(
        "Method Letter Acc. Input: foo bar"
    ) == "table"
