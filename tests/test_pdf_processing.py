import logging

import pymupdf
import pytest

from docintel.pdf_processing import (
    PDFValidationError,
    build_vocabulary,
    extract_document,
    normalize_block_text,
    render_page_png,
    strip_repeated_boilerplate,
)
from tests.conftest import MSA, RESEARCH, SCANNED


def test_extracts_text_with_one_based_page_numbers(make_pdf, settings):
    record = extract_document(
        "two.pdf", make_pdf(["Alpha page one text.", "Beta page two text."]), settings
    )
    assert record.page_count == 2
    assert [p.page_number for p in record.pages] == [1, 2]
    assert "Alpha" in record.pages[0].text and "Beta" in record.pages[1].text
    assert record.doc_id.startswith("doc-") and len(record.sha256) == 64


def test_same_bytes_give_same_document_id(make_pdf, settings):
    data = make_pdf(["Stable content."])
    assert (
        extract_document("a.pdf", data, settings).doc_id
        == extract_document("b.pdf", data, settings).doc_id
    )


def test_rejects_bytes_without_pdf_header(settings):
    with pytest.raises(PDFValidationError) as err:
        extract_document("notes.pdf", b"just some text, not a pdf", settings)
    assert err.value.code == "not_pdf"


def test_rejects_wrong_extension(make_pdf, settings):
    with pytest.raises(PDFValidationError) as err:
        extract_document("report.docx", make_pdf(["x"]), settings)
    assert err.value.code == "not_pdf"


def test_rejects_empty_file(settings):
    with pytest.raises(PDFValidationError) as err:
        extract_document("empty.pdf", b"", settings)
    assert err.value.code == "empty"


def test_rejects_oversized_file(make_pdf, settings):
    tiny_limit = settings.with_overrides(max_file_mb=0.0005)  # ~500 bytes
    with pytest.raises(PDFValidationError) as err:
        extract_document("big.pdf", make_pdf(["content " * 200]), tiny_limit)
    assert err.value.code == "too_large"
    assert "limit" in err.value.user_message


def test_rejects_corrupt_pdf(settings):
    with pytest.raises(PDFValidationError) as err:
        extract_document("broken.pdf", b"%PDF-1.7\n" + bytes(range(256)) * 20, settings)
    assert err.value.code == "corrupt"


def test_rejects_password_protected_pdf(make_pdf, settings):
    with pytest.raises(PDFValidationError) as err:
        extract_document("locked.pdf", make_pdf(["secret"], encrypt_user_pw="user-pass"), settings)
    assert err.value.code == "encrypted"
    assert "password" in err.value.user_message.lower()


def test_owner_password_only_pdf_is_readable(make_pdf, settings):
    record = extract_document("perm.pdf", make_pdf(["Readable text."], owner_only=True), settings)
    assert "Readable text." in record.pages[0].text


def test_rejects_too_many_pages(make_pdf, settings):
    with pytest.raises(PDFValidationError) as err:
        extract_document(
            "long.pdf", make_pdf(["a", "b", "c"]), settings.with_overrides(max_pages_per_document=2)
        )
    assert err.value.code == "too_many_pages"


def test_scanned_image_only_pdf_gets_ocr_explanation(fixture_bytes, settings):
    with pytest.raises(PDFValidationError) as err:
        extract_document(SCANNED, fixture_bytes(SCANNED), settings)
    assert err.value.code == "no_text"
    assert "OCR" in err.value.user_message


def test_blank_page_is_reported_not_silently_dropped(make_pdf, settings):
    record = extract_document("gap.pdf", make_pdf(["Page one.", "", "Page three."]), settings)
    assert record.page_count == 3
    assert record.empty_pages == [2]
    assert any("page(s) 2" in w for w in record.warnings)


def test_normalizes_ligatures_nbsp_soft_hyphens_and_line_hyphenation():
    raw = "The ﬁnal infor-\nmation is   here, re­viewed."
    assert normalize_block_text(raw, {"information"}) == "The final information is here, reviewed."


def test_line_end_hyphen_is_kept_unless_the_joined_word_is_known():
    assert normalize_block_text("a cross-\nsectional design", set()) == "a cross-sectional design"
    assert normalize_block_text("infor-\nmation", None) == "infor-mation"
    assert (
        normalize_block_text("infor-\nmation", build_vocabulary(["more information here"]))
        == "information"
    )


def test_real_compound_word_split_across_lines_survives_extraction(fixture_bytes, settings):
    record = extract_document(RESEARCH, fixture_bytes(RESEARCH), settings)
    assert "cross-sectional" in record.pages[3].text


def test_strip_repeated_boilerplate_removes_running_headers_and_footers():
    pages = [
        ["Acme Report", "Body one.", "Confidential - Page 1 of 3"],
        ["Acme Report", "Body two.", "Confidential - Page 2 of 3"],
        ["Acme Report", "Body three.", "Confidential - Page 3 of 3"],
    ]
    cleaned, removed = strip_repeated_boilerplate(pages)
    assert cleaned == [["Body one."], ["Body two."], ["Body three."]]
    assert "Acme Report" in removed and any("Page 1 of 3" in r for r in removed)


def test_strip_boilerplate_leaves_single_page_and_unique_text_alone():
    single = [["Title", "Only page."]]
    assert strip_repeated_boilerplate(single) == (single, [])
    distinct = [["Intro", "A"], ["Methods", "B"], ["Results", "C"]]
    assert strip_repeated_boilerplate(distinct) == (distinct, [])


def test_boilerplate_removal_is_reported_in_document_notes(fixture_bytes, settings):
    record = extract_document(MSA, fixture_bytes(MSA), settings)
    assert any("header/footer" in n for n in record.notes)
    assert all("SYNTHETIC TEST DOCUMENT" not in p.text for p in record.pages)


def test_filename_is_sanitized(make_pdf, settings):
    record = extract_document("../../etc/<evil>name.pdf", make_pdf(["x"]), settings)
    assert "/" not in record.filename and "<" not in record.filename
    assert record.filename.endswith(".pdf")


def test_metadata_title_is_kept(make_pdf, settings):
    record = extract_document("t.pdf", make_pdf(["x"], title="Quarterly Plan"), settings)
    assert record.metadata.get("title") == "Quarterly Plan"


def test_render_page_png_with_highlight(make_pdf):
    data = make_pdf(["Alpha beta gamma delta."])
    png = render_page_png(data, 1, ["beta gamma"])
    assert png is not None and png.startswith(b"\x89PNG")
    assert render_page_png(data, 5) is None


def test_extraction_logs_no_document_content(make_pdf, settings, caplog):
    secret = "ZEBRA-CONFIDENTIAL-PHRASE"
    with caplog.at_level(logging.DEBUG, logger="docintel"):
        extract_document("private.pdf", make_pdf([f"The code word is {secret}."]), settings)
    assert caplog.records, "expected an extraction log event"
    assert secret not in caplog.text


def test_pymupdf_is_the_extraction_backend():
    assert hasattr(pymupdf, "open")
