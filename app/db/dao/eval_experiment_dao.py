from app.db.base_dao import BaseDAO
from app.models.eval import EvalExperiment


class EvalExperimentDAO(BaseDAO[EvalExperiment]):
    def __init__(self) -> None:
        super().__init__(EvalExperiment)


eval_experiment_dao = EvalExperimentDAO()
