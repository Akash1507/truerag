from unittest.mock import MagicMock, patch

import pytest

from app.core.errors import ParseError
from app.pipelines.ingestion.parser import parse_document


def test_parse_txt_returns_utf8_text() -> None:
    content = "Hello, World!".encode("utf-8")
    result = parse_document(content, "txt")
    assert result == "Hello, World!"


def test_parse_md_returns_utf8_text() -> None:
    content = "# Header\n\nSome markdown text.".encode("utf-8")
    result = parse_document(content, "md")
    assert result == "# Header\n\nSome markdown text."


def test_parse_pdf_extracts_text() -> None:
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Page one content"
    mock_reader = MagicMock()
    mock_reader.pages = [mock_page]

    with patch("app.pipelines.ingestion.parser.pypdf.PdfReader", return_value=mock_reader):
        result = parse_document(b"%PDF-fake", "pdf")

    assert result == "Page one content"


def test_parse_docx_extracts_paragraphs() -> None:
    mock_para1 = MagicMock()
    mock_para1.text = "First paragraph"
    mock_para2 = MagicMock()
    mock_para2.text = "Second paragraph"
    mock_doc = MagicMock()
    mock_doc.paragraphs = [mock_para1, mock_para2]

    with patch("app.pipelines.ingestion.parser.docx.Document", return_value=mock_doc):
        result = parse_document(b"PK\x03\x04fake-docx", "docx")

    assert result == "First paragraph\nSecond paragraph"


def test_parse_unsupported_file_type_raises_parse_error() -> None:
    with pytest.raises(ParseError):
        parse_document(b"some,csv,data", "csv")


def test_parse_corrupt_bytes_raises_parse_error() -> None:
    invalid_utf8 = b"\xff\xfe invalid bytes"
    with pytest.raises(ParseError):
        parse_document(invalid_utf8, "txt")
