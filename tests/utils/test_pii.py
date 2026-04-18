from unittest.mock import MagicMock, patch

import pytest

from app.core.errors import ProviderUnavailableError
from app.utils.pii import scrub_pii


def test_scrub_pii_no_pii_returns_unchanged() -> None:
    text = "No sensitive information here"
    with (
        patch("app.utils.pii._analyzer") as mock_analyzer,
        patch("app.utils.pii._anonymizer"),
    ):
        mock_analyzer.analyze.return_value = []
        result = scrub_pii(text)
    assert result == text


def test_scrub_pii_replaces_person_entity() -> None:
    mock_result = MagicMock()
    mock_anonymized = MagicMock()
    mock_anonymized.text = "<PERSON> is here"

    with (
        patch("app.utils.pii._analyzer") as mock_analyzer,
        patch("app.utils.pii._anonymizer") as mock_anon,
    ):
        mock_analyzer.analyze.return_value = [mock_result]
        mock_anon.anonymize.return_value = mock_anonymized
        result = scrub_pii("John Smith is here")

    assert result == "<PERSON> is here"
    assert "John Smith" not in result


def test_scrub_pii_replaces_email() -> None:
    mock_result = MagicMock()
    mock_anonymized = MagicMock()
    mock_anonymized.text = "Contact me at <EMAIL_ADDRESS>"

    with (
        patch("app.utils.pii._analyzer") as mock_analyzer,
        patch("app.utils.pii._anonymizer") as mock_anon,
    ):
        mock_analyzer.analyze.return_value = [mock_result]
        mock_anon.anonymize.return_value = mock_anonymized
        result = scrub_pii("Contact me at user@example.com")

    assert "user@example.com" not in result


def test_scrub_pii_replaces_phone_number() -> None:
    mock_result = MagicMock()
    mock_anonymized = MagicMock()
    mock_anonymized.text = "Call me at <PHONE_NUMBER>"

    with (
        patch("app.utils.pii._analyzer") as mock_analyzer,
        patch("app.utils.pii._anonymizer") as mock_anon,
    ):
        mock_analyzer.analyze.return_value = [mock_result]
        mock_anon.anonymize.return_value = mock_anonymized
        result = scrub_pii("Call me at +1-555-123-4567")

    assert "+1-555-123-4567" not in result


def test_scrub_pii_raises_provider_unavailable_on_analyzer_error() -> None:
    with (
        patch("app.utils.pii._analyzer") as mock_analyzer,
        patch("app.utils.pii._anonymizer"),
    ):
        mock_analyzer.analyze.side_effect = RuntimeError("spacy model not loaded")
        with pytest.raises(ProviderUnavailableError):
            scrub_pii("some text")


def test_scrub_pii_passes_document_id_to_logger() -> None:
    mock_result = MagicMock()
    mock_anonymized = MagicMock()
    mock_anonymized.text = "redacted"

    with (
        patch("app.utils.pii._analyzer") as mock_analyzer,
        patch("app.utils.pii._anonymizer") as mock_anon,
        patch("app.utils.pii.logger") as mock_logger,
    ):
        mock_analyzer.analyze.return_value = [mock_result]
        mock_anon.anonymize.return_value = mock_anonymized
        scrub_pii("John Smith", document_id="doc-123")

    mock_logger.info.assert_called_once()
    call_kwargs = mock_logger.info.call_args
    extra = call_kwargs[1]["extra"] if "extra" in call_kwargs[1] else call_kwargs[0][1]["extra"]
    assert extra["extra_data"]["document_id"] == "doc-123"
    assert extra["extra_data"]["entities_found"] == 1
