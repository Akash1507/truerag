from app.db.base_dao import BaseDAO
from app.models.ingestion_job import IngestionJob


class IngestionJobDAO(BaseDAO[IngestionJob]):
    def __init__(self) -> None:
        super().__init__(IngestionJob)


ingestion_job_dao = IngestionJobDAO()
