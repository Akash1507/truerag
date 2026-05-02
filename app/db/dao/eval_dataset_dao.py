from app.db.base_dao import BaseDAO
from app.models.eval import EvalDataset


class EvalDatasetDAO(BaseDAO[EvalDataset]):
    def __init__(self) -> None:
        super().__init__(EvalDataset)


eval_dataset_dao = EvalDatasetDAO()
