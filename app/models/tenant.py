from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TenantDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    tenant_id: str
    api_key_hash: str
    rate_limit_rpm: int | None = None
    created_at: datetime
