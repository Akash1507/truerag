import io

import docx
import pypdf

from app.core.errors import ParseError


def parse_document(content: bytes, file_type: str) -> str:
    match file_type:
        case "txt" | "md":
            return _parse_text(content)
        case "pdf":
            return _parse_pdf(content)
        case "docx":
            return _parse_docx(content)
        case _:
            raise ParseError(f"Unsupported file type for pipeline parsing: {file_type}")


def _parse_text(content: bytes) -> str:
    try:
        text = content.decode("utf-8")
        if not text.strip():
            raise ParseError("Text document has no text")
        return text
    except Exception as e:
        if isinstance(e, ParseError):
            raise
        raise ParseError(f"Text decode failed: {e}") from e


def _parse_pdf(content: bytes) -> str:
    text = _parse_pdf_pymupdf(content) or _parse_pdf_pypdf(content)
    if not text or not text.strip():
        raise ParseError("PDF produced no text — may be a scanned/image-only PDF")
    return text


def _parse_pdf_pymupdf(content: bytes) -> str | None:
    try:
        import fitz  # pymupdf
        doc = fitz.open(stream=content, filetype="pdf")
        pages = [page.get_text() for page in doc]
        doc.close()
        return "\n".join(pages)
    except Exception:
        return None


def _parse_pdf_pypdf(content: bytes) -> str | None:
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        if not reader.pages:
            return None
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return None


def _parse_docx(content: bytes) -> str:
    try:
        doc = docx.Document(io.BytesIO(content))
        if not doc.paragraphs:
            raise ParseError("DOCX has no paragraphs")
        text = "\n".join(p.text for p in doc.paragraphs)
        if not text.strip():
            raise ParseError("DOCX produced no text")
        return text
    except Exception as exc:
        if isinstance(exc, ParseError):
            raise
        raise ParseError(f"DOCX parse failed: {exc}") from exc
