from unittest.mock import MagicMock, patch

from app.pipelines.ingestion.parser import parse_document


def test_parse_pdf_uses_ocr_fallback_for_scanned_documents() -> None:
    mock_tesseract = MagicMock()
    mock_tesseract.image_to_string.side_effect = ["OCR page one", "OCR page two"]
    mock_tesseract.TesseractNotFoundError = RuntimeError

    with (
        patch("app.pipelines.ingestion.parser._parse_pdf_pymupdf", return_value="too short"),
        patch("app.pipelines.ingestion.parser._parse_pdf_pypdf", return_value="tiny"),
        patch(
            "app.pipelines.ingestion.parser.convert_from_bytes",
            return_value=["image-1", "image-2"],
        ) as mock_convert,
        patch("app.pipelines.ingestion.parser.pytesseract", mock_tesseract),
        patch("app.pipelines.ingestion.parser.logger") as mock_logger,
    ):
        result = parse_document(b"%PDF-fake", "pdf")

    assert result == "OCR page one\n\nOCR page two"
    mock_convert.assert_called_once_with(b"%PDF-fake", dpi=300)

    ocr_calls = [c for c in mock_logger.info.call_args_list if c.args and c.args[0] == "ocr_fallback"]
    assert len(ocr_calls) == 1
    assert ocr_calls[0].kwargs["extra"]["extra_data"]["page_count"] == 2
    assert ocr_calls[0].kwargs["extra"]["extra_data"]["char_count"] == len(result)
