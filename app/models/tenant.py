from datetime import datetime
from typing import Annotated, Literal

from beanie import Document
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

TenantName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=100,
        strip_whitespace=True,
        pattern=r"^[a-zA-Z0-9_-]+$",
    ),
]


class TenantDocument(Document):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    tenant_id: str
    name: str
    display_name: str | None = None
    api_key_hash: str
    rate_limit_rpm: int | None = None
    role: Literal["admin", "agent_owner", "reader"] = "agent_owner"
    monthly_token_budget: int | None = Field(default=None, ge=1)
    created_at: datetime

    class Settings:
        name = "tenants"


class TenantCreateRequest(BaseModel):
    name: TenantName
    display_name: str | None = None


class TenantCreateResponse(BaseModel):
    tenant_id: str
    name: str
    display_name: str | None = None
    api_key: str
    rate_limit_rpm: int
    created_at: datetime


class TenantListItem(BaseModel):
    tenant_id: str
    name: str
    display_name: str | None = None
    rate_limit_rpm: int
    created_at: datetime


class TenantListResponse(BaseModel):
    items: list[TenantListItem]
    next_cursor: str | None


class TenantBudgetUpdateRequest(BaseModel):
    monthly_token_budget: int | None = Field(default=None, ge=1)


class TenantBudgetResponse(BaseModel):
    tenant_id: str
    name: str
    display_name: str | None = None
    rate_limit_rpm: int | None = None
    role: Literal["admin", "agent_owner", "reader"]
    monthly_token_budget: int | None
    created_at: datetime


class TenantUpdateRequest(BaseModel):
    display_name: str | None = None
    role: Literal["admin", "agent_owner", "reader"] | None = None
    monthly_token_budget: int | None = Field(default=None, ge=1)


class TenantUpdateResponse(BaseModel):
    tenant_id: str
    name: str
    display_name: str | None
    role: Literal["admin", "agent_owner", "reader"]
    monthly_token_budget: int | None
    created_at: datetime


class MeResponse(BaseModel):
    tenant_id: str
    name: str
    display_name: str | None
    role: str


class AdminTenantItem(BaseModel):
    tenant_id: str
    name: str
    display_name: str | None
    role: str
    monthly_token_budget: int | None
    created_at: datetime
    agent_count: int


class AdminTenantListResponse(BaseModel):
    items: list[AdminTenantItem]
    total: int
