from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

TenantName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=100,
        strip_whitespace=True,
        pattern=r"^[a-zA-Z0-9_-]+$",
    ),
]


class TenantDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    tenant_id: str
    name: str
    api_key_hash: str
    rate_limit_rpm: int | None = None
    created_at: datetime


class TenantCreateRequest(BaseModel):
    name: TenantName


class TenantCreateResponse(BaseModel):
    tenant_id: str
    name: str
    api_key: str
    rate_limit_rpm: int
    created_at: datetime


class TenantListItem(BaseModel):
    tenant_id: str
    name: str
    rate_limit_rpm: int
    created_at: datetime


class TenantListResponse(BaseModel):
    items: list[TenantListItem]
    next_cursor: str | None
