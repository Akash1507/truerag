from app.db.base_dao import BaseDAO
from app.models.document import DocumentRecord


class DocumentDAO(BaseDAO[DocumentRecord]):
    def __init__(self) -> None:
        super().__init__(DocumentRecord)


document_dao = DocumentDAO()
