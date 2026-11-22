"""Tests for the FastAPI GET /health endpoint."""

from httpx import AsyncClient


async def test_root_endpoint_returns_service_info(api_client: AsyncClient) -> None:
    """GET / returns 200 with service metadata and endpoint links."""
    response = await api_client.get("/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["health"] == "/health"


async def test_health_endpoint_returns_ok(api_client: AsyncClient) -> None:
    """GET /health returns 200 with ok status for both PostgreSQL and Redis."""
    response = await api_client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"] == "ok"
    assert payload["redis"] == "ok"
    assert isinstance(payload["version"], str)
