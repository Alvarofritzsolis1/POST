from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AccountInput(Input):
    name: str = Field(min_length=2, max_length=180)
    email: EmailStr
    title: str = Field(default="", max_length=180)
    role: Literal["admin", "resident"] = "resident"
    enabled: bool = True
    site_ids: list[str] = Field(default_factory=list, max_length=100)
    can_award: bool = False

    @field_validator("email")
    @classmethod
    def lower_email(cls, value):
        return str(value).lower()

    @model_validator(mode="after")
    def assigned(self):
        if self.role == "resident" and not self.site_ids:
            raise ValueError("Asigna al menos una obra al residente")
        if len(self.site_ids) != len(set(self.site_ids)):
            raise ValueError("Las obras no se pueden repetir")
        return self


class AccountEdit(Input):
    name: str = Field(min_length=2, max_length=180)
    title: str = Field(default="", max_length=180)
    role: Literal[
        "admin",
        "resident",
        "supervisor",
        "reviewer",
        "administrative",
        "viewer",
        "analyst",
    ]
    enabled: bool
    site_ids: list[str] = Field(default_factory=list, max_length=100)
    can_award: bool = False


class SetPassword(Input):
    token: str = Field(min_length=30, max_length=200)
    password: str = Field(min_length=12, max_length=256)


class ForgotPassword(Input):
    email: EmailStr


class Dated(Input):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def dates(self):
        if self.end_date < self.start_date:
            raise ValueError("La fecha de término debe ser posterior o igual al inicio")
        return self


Quantity = Field(gt=0, max_digits=14, decimal_places=3)


class ItemInput(Dated):
    id: str | None = None
    name: str = Field(min_length=2, max_length=180)
    description: str = Field(default="", max_length=5000)
    quantity: Decimal = Quantity
    unit: str = Field(min_length=1, max_length=24)
    notes: str = Field(default="", max_length=2000)


class RequirementInput(Dated):
    site_id: str
    specialty: str = Field(min_length=2, max_length=100)
    title: str = Field(min_length=3, max_length=180)
    description: str = Field(default="", max_length=10000)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    workers: int = Field(ge=1, le=10000)
    deadline: date
    state: Literal["draft", "published", "cancelled"] = "published"
    items: list[ItemInput] = Field(min_length=1)
    client_key: str = Field(
        default_factory=lambda: str(uuid4()), min_length=8, max_length=80
    )
    version: int | None = Field(default=None, ge=1)
    reason: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def scheduling(self):
        if self.deadline > self.end_date:
            raise ValueError("El plazo límite no puede ser posterior al término")
        if any(
            i.start_date < self.start_date or i.end_date > self.end_date
            for i in self.items
        ):
            raise ValueError(
                "Las fechas de cada partida deben estar dentro del requerimiento"
            )
        return self


class PendingItem(Input):
    name: str = Field(min_length=2, max_length=180)
    quantity: Decimal = Quantity
    unit: str = Field(min_length=1, max_length=24)
    end_date: date


class CapacityInput(Input):
    site_id: str
    contractor_id: str
    specialty: str = Field(min_length=2, max_length=100)
    situation: Literal["few_pending", "ending", "partial", "finished", "unconfirmed"]
    available_date: date
    workers: int = Field(ge=1, le=10000)
    mode: Literal["partial", "total"] = "total"
    availability: Literal[
        "estimated", "pending", "confirmed", "discarded", "committed"
    ] = "estimated"
    notes: str = Field(default="", max_length=5000)
    can_transfer: bool = True
    state: Literal["draft", "published"] = "published"
    validity_days: int = Field(default=14, ge=1, le=90)
    pending_items: list[PendingItem] = Field(default_factory=list)
    version: int | None = Field(default=None, ge=1)
    client_key: str = Field(
        default_factory=lambda: str(uuid4()), min_length=8, max_length=80
    )


class InterestInput(Input):
    match_id: str


class CoordinationEdit(Input):
    state: Literal[
        "contacted",
        "evaluating",
        "confirmed",
        "proposed",
        "approved",
        "documents_pending",
        "documents_complete",
        "finished",
        "rejected",
        "cancelled",
    ]
    version: int = Field(ge=1)
    reason: str = Field(default="", max_length=2000)


class MessageInput(Input):
    body: str = Field(min_length=1, max_length=10000)
    client_key: str = Field(min_length=8, max_length=80)


class ParticipantInput(Input):
    user_id: str


class AwardInput(Dated):
    item_id: str
    contractor_id: str
    quantity: Decimal = Quantity
    capacity_id: str | None = None
    coordination_id: str | None = None
    workers: int = Field(default=0, ge=0, le=10000)
    notes: str = Field(default="", max_length=5000)
    client_key: str = Field(min_length=8, max_length=80)
    acknowledge_conflict: bool = False
    conflict_reason: str = Field(default="", max_length=2000)


class AwardEdit(Input):
    state: Literal["assigned", "ready", "in_progress", "completed", "revoked"]
    executed: Decimal = Field(ge=0, max_digits=14, decimal_places=3)
    version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=2000)


class AmendmentInput(Input):
    quantity: Decimal = Quantity
    reason: str = Field(min_length=5, max_length=2000)


class AwardRevision(Dated):
    quantity: Decimal = Quantity
    version: int = Field(ge=1)
    reason: str = Field(min_length=5, max_length=2000)
    acknowledge_conflict: bool = False
    conflict_reason: str = Field(default="", max_length=2000)


class NetworkProfile(Input):
    name: str = Field(min_length=2, max_length=180)
    title: str = Field(default="", max_length=180)
    notifications: bool = True


class Renewal(Input):
    validity_days: int = Field(default=14, ge=1, le=90)
    version: int = Field(ge=1)
