from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.core.models.tariff import Tariff


async def get_tariffs(session: AsyncSession) -> Sequence[Tariff]:
    result = await session.scalars(select(Tariff).order_by(Tariff.id))
    return result.all()


async def sync_tariff_prices(
    session: AsyncSession, prices: dict[str, int]
) -> list[tuple[str, int | None, int]]:
    statement = insert(Tariff).values(
        [{"title": title, "price": price} for title, price in sorted(prices.items())]
    )
    # Insert first so concurrent initializers also lock newly created tariffs.
    created = set(
        await session.scalars(
            statement.on_conflict_do_nothing(index_elements=[Tariff.title]).returning(
                Tariff.title
            )
        )
    )
    previous_rows = await session.execute(
        select(Tariff.title, Tariff.price)
        .where(Tariff.title.in_(prices))
        .order_by(Tariff.title)
        .with_for_update()
    )
    previous = dict(previous_rows.tuples().all())
    updated = await session.execute(
        statement.on_conflict_do_update(
            index_elements=[Tariff.title],
            set_={"price": statement.excluded.price},
            where=Tariff.price != statement.excluded.price,
        ).returning(Tariff.title, Tariff.price)
    )
    changes: list[tuple[str, int | None, int]] = [
        (title, None, prices[title]) for title in sorted(created)
    ]
    for title, price in updated:
        changes.append((title, previous[title], price))
    return changes
