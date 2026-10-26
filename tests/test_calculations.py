import pytest

from payment_service.services.calculations import calculate_payment


@pytest.mark.parametrize(
    ("price", "promo_code", "amount", "discount"),
    [
        (1990000, None, 1990000, 0),
        (1990000, "KVITTO10", 1791000, 199000),
        (1990000, "kvitto10", 1791000, 199000),
        (1990000, "KvItTo10", 1791000, 199000),
        (19, "KVITTO10", 18, 1),
        (9007199254741001, "KVITTO10", 8106479329266901, 900719925474100),
    ],
)
def test_payment_amount_and_discount(
    price: int, promo_code: str | None, amount: int, discount: int
) -> None:
    result = calculate_payment(price, promo_code=promo_code)

    assert result.amount == amount
    assert result.discount == discount
    assert result.amount + result.discount == price
    assert type(result.amount) is type(result.discount) is int
    assert result.schedule is None


@pytest.mark.parametrize(
    ("months", "schedule"),
    [
        (3, [663334, 663333, 663333]),
        (6, [331667, 331667, 331667, 331667, 331666, 331666]),
        (12, [165834] * 4 + [165833] * 8),
    ],
)
def test_standard_installment_schedule(months: int, schedule: list[int]) -> None:
    result = calculate_payment(1990000, installment_months=months)

    assert result.schedule == schedule


@pytest.mark.parametrize("months", [3, 6, 12])
@pytest.mark.parametrize(
    ("price", "promo_code"),
    [(1990000, "kvitto10"), (7, None), (9007199254740993, None)],
)
def test_schedule_preserves_amount(
    price: int, promo_code: str | None, months: int
) -> None:
    result = calculate_payment(price, promo_code=promo_code, installment_months=months)

    assert result.schedule is not None
    assert len(result.schedule) == months
    assert sum(result.schedule) == result.amount
    assert all(type(payment) is int and payment >= 0 for payment in result.schedule)
    assert result.schedule == sorted(result.schedule, reverse=True)
    assert max(result.schedule) - min(result.schedule) <= 1
