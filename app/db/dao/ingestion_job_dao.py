from pymongo import ReturnDocument

from app.db.base_dao import BaseDAO
from app.models.document import DocumentStatus
from app.models.ingestion_job import IngestionJob


class IngestionJobDAO(BaseDAO[IngestionJob]):
    def __init__(self) -> None:
        super().__init__(IngestionJob)

    async def set_processing(self, job_id: str) -> bool:
        updated = await IngestionJob.get_motor_collection().find_one_and_update(
            {"job_id": job_id, "status": DocumentStatus.queued},
            {"$set": {"status": DocumentStatus.processing}},
            return_document=ReturnDocument.AFTER,
        )
        return updated is not None

    async def get_retriable_failed(self, max_retries: int) -> list[IngestionJob]:
        return await IngestionJob.find(
            {"status": DocumentStatus.failed, "retry_count": {"$lte": max_retries}}
        ).to_list()

    async def increment_retry_count(self, job_id: str) -> None:
        await IngestionJob.get_motor_collection().update_one(
            {"job_id": job_id},
            {"$inc": {"retry_count": 1}},
        )


ingestion_job_dao = IngestionJobDAO()
