from unittest.mock import MagicMock, patch

from app.pipelines.ingestion.parser import parse_document


def test_parse_pdf_appends_table_text_when_available() -> None:
    body_text = "A" * 60
    table_text = "| col1 | col2 |\n| v1 | v2 |"

    with (
        patch("app.pipelines.ingestion.parser._parse_pdf_pymupdf", return_value=body_text),
        patch("app.pipelines.ingestion.parser._parse_pdf_pypdf", return_value=""),
        patch("app.pipelines.ingestion.parser._extract_pdf_tables", return_value=table_text),
    ):
        result = parse_document(b"%PDF-table", "pdf")

    assert result == f"{body_text}\n\n---TABLE---\n{table_text}"


def test_parse_pdf_table_extraction_failure_is_non_fatal() -> None:
    body_text = "B" * 60

    with (
        patch("app.pipelines.ingestion.parser._parse_pdf_pymupdf", return_value=body_text),
        patch("app.pipelines.ingestion.parser._parse_pdf_pypdf", return_value=""),
        patch("app.pipelines.ingestion.parser._extract_pdf_tables", side_effect=RuntimeError("boom")),
        patch("app.pipelines.ingestion.parser.logger") as mock_logger,
    ):
        result = parse_document(b"%PDF-table", "pdf")

    assert result == body_text
    mock_logger.warning.assert_called_once()


def test_parse_docx_appends_table_rows_after_paragraphs() -> None:
    paragraph = MagicMock(text="Summary")

    row_1 = MagicMock()
    row_1.cells = [MagicMock(text="h1"), MagicMock(text="h2")]
    row_2 = MagicMock()
    row_2.cells = [MagicMock(text="v1"), MagicMock(text="v2")]

    table = MagicMock()
    table.rows = [row_1, row_2]

    doc = MagicMock()
    doc.paragraphs = [paragraph]
    doc.tables = [table]

    with patch("app.pipelines.ingestion.parser.docx.Document", return_value=doc):
        result = parse_document(b"PK-fake", "docx")

    assert result == "Summary\n\n---TABLE---\n| h1 | h2 |\n| v1 | v2 |"
