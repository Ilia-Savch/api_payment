import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from payment_service.core.models.payment import PaymentMethod
from payment_service.core.schemas.payment import PaymentCreate
from payment_service.services.calculations import PROMO_CODES, calculate_payment


@pytest.mark.parametrize(
    ("code", "percent", "discount", "amount"),
    [("summer20", 20, 2469, 9876), ("Autumn25", 25, 3086, 9259)],
)
def test_added_promo_code_is_validated_and_calculated(
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    percent: int,
    discount: int,
    amount: int,
) -> None:
    monkeypatch.setitem(PROMO_CODES, code.upper(), percent)
    payment = PaymentCreate.model_validate(
        {
            "tariff_id": 1,
            "email": "payer@example.com",
            "method": "installment",
            "installment_months": 3,
            "promo_code": code,
        }
    )

    result = calculate_payment(
        12345,
        promo_code=payment.promo_code,
        installment_months=payment.installment_months,
    )

    assert payment.promo_code == code.upper()
    assert result.discount == discount
    assert result.amount == amount
    assert result.schedule is not None
    assert sum(result.schedule) == amount


@pytest.mark.parametrize(
    ("method", "months", "expected_months"),
    [
        ("card", None, None),
        ("sbp", None, None),
        ("card", 3, None),
        ("installment", 3, 3),
        ("installment", 6, 6),
        ("installment", 12, 12),
    ],
)
def test_valid_payment_request(
    method: str, months: int | None, expected_months: int | None
) -> None:
    payment = PaymentCreate.model_validate(
        {
            "tariff_id": 1,
            "email": "payer@example.com",
            "method": method,
            "installment_months": months,
            "promo_code": "kvitto10",
            "amount": 1,
            "discount": 0,
            "status": "succeeded",
            "schedule": [1],
        }
    )

    assert payment.method == PaymentMethod(method)
    assert payment.installment_months == expected_months
    assert payment.promo_code == "KVITTO10"
    assert not {"amount", "discount", "status", "schedule"} & payment.model_fields_set


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("fields", "error_field"),
    [
        ({"email": "not-an-email"}, "email"),
        ({"method": "cash"}, "method"),
        ({"promo_code": "UNKNOWN"}, "promo_code"),
        ({"promo_code": ""}, "promo_code"),
        ({"method": "installment"}, None),
        ({"method": "installment", "installment_months": None}, None),
        ({"method": "installment", "installment_months": 0}, "installment_months"),
        ({"method": "installment", "installment_months": 4}, "installment_months"),
        ({"method": "installment", "installment_months": 24}, "installment_months"),
    ],
)
async def test_invalid_payment_returns_standard_422(
    fields: dict[str, object], error_field: str | None
) -> None:
    application = FastAPI()

    @application.post("/validate")
    async def validate(payment: PaymentCreate) -> dict[str, bool]:
        return {"valid": True}

    payload = {"tariff_id": 1, "email": "payer@example.com", "method": "card"}
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://testserver"
    ) as client:
        response = await client.post("/validate", json={**payload, **fields})

    assert response.status_code == 422
    errors = response.json()["detail"]
    assert len(errors) == 1
    expected_location = ["body", error_field] if error_field else ["body"]
    assert errors[0]["loc"] == expected_location
    assert {"type", "msg", "input"} <= errors[0].keys()
