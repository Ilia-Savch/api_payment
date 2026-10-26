from datetime import datetime
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    field_validator,
    model_validator,
)

from payment_service.core.models.payment import PaymentMethod, PaymentStatus
from payment_service.services.calculations import validate_promo_code

InstallmentMonths = Literal[3, 6, 12]


class PaymentCreate(BaseModel):
    tariff_id: int
    email: EmailStr
    method: PaymentMethod
    installment_months: InstallmentMonths | None = None
    promo_code: str | None = None

    @field_validator("promo_code")
    @classmethod
    def check_promo_code(cls, value: str | None) -> str | None:
        return validate_promo_code(value)

    @model_validator(mode="after")
    def check_installment_months(self) -> Self:
        if self.method == PaymentMethod.INSTALLMENT:
            if self.installment_months is None:
                raise ValueError("installment_months is required for installment")
        else:
            self.installment_months = None
        return self


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: PaymentStatus
    tariff_id: int
    amount: int
    discount: int
    method: PaymentMethod
    installment_months: InstallmentMonths | None
    schedule: list[int] | None
    email: EmailStr
    created_at: datetime
