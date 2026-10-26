import pytest
from httpx import ASGITransport, AsyncClient

from payment_service.main import app


@pytest.mark.anyio
async def test_application_serves_openapi() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "Payments API"
    assert schema["openapi"].startswith("3.")
