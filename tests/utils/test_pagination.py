import pytest
from bson import ObjectId

from app.utils.pagination import decode_cursor, encode_cursor


def test_encode_decode_cursor_round_trip() -> None:
    original_id = ObjectId()
    cursor = encode_cursor(original_id)
    assert isinstance(cursor, str)
    assert len(cursor) > 0

    decoded_id = decode_cursor(cursor)
    assert decoded_id == original_id


def test_decode_cursor_invalid_format() -> None:
    with pytest.raises(ValueError, match="Invalid cursor"):
        decode_cursor("not-base64-encoded")


def test_decode_cursor_invalid_objectid() -> None:
    import base64
    # Valid base64, but not a valid ObjectId string
    invalid_ObjectId_cursor = base64.urlsafe_b64encode(b"invalid-id").decode()
    with pytest.raises(ValueError, match="Invalid cursor"):
        decode_cursor(invalid_ObjectId_cursor)
