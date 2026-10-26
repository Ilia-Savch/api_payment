from dataclasses import dataclass

PROMO_CODES: dict[str, int] = {"KVITTO10": 10}


def validate_promo_code(promo_code: str | None) -> str | None:
    if promo_code is None:
        return None
    normalized_code = promo_code.upper()
    if normalized_code not in PROMO_CODES:
        raise ValueError("Unknown promo code")
    return normalized_code


@dataclass(frozen=True)
class PaymentCalculation:
    amount: int
    discount: int
    schedule: list[int] | None


def calculate_payment(
    price: int,
    *,
    promo_code: str | None = None,
    installment_months: int | None = None,
) -> PaymentCalculation:
    """Calculate money for a validated request; discard fractional discount kopecks."""
    code = validate_promo_code(promo_code)
    discount_percent = PROMO_CODES[code] if code is not None else 0
    discount = price * discount_percent // 100
    amount = price - discount
    schedule = None
    if installment_months is not None:
        payment, remainder = divmod(amount, installment_months)
        schedule = [
            payment + (index < remainder) for index in range(installment_months)
        ]
    return PaymentCalculation(amount=amount, discount=discount, schedule=schedule)
