import base64

from bson import ObjectId

DEFAULT_PAGE_SIZE: int = 20


def encode_cursor(object_id: ObjectId) -> str:
    return base64.urlsafe_b64encode(str(object_id).encode()).decode()


def decode_cursor(cursor: str) -> ObjectId:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        return ObjectId(raw)
    except Exception as exc:
        raise ValueError(f"Invalid cursor: {cursor!r}") from exc
