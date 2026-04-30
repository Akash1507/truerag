from app.db.base_dao import BaseDAO
from app.models.tenant import TenantDocument


class TenantDAO(BaseDAO[TenantDocument]):
    def __init__(self) -> None:
        super().__init__(TenantDocument)


tenant_dao = TenantDAO()
