"""Light integration tests against the FastAPI app (no Kapso / network calls)."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_returns_service_info() -> None:
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data.get("service")
    assert data.get("docs") == "/docs"


def test_health_returns_healthy() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data
    assert "environment" in data


@patch("app.services.monito_playwright_service.MonitoPlaywrightService")
def test_monito_compare_returns_json(mock_svc_class: object) -> None:
    mock_inst = mock_svc_class.return_value
    mock_inst.compare = AsyncMock(
        return_value=[{"rank": 1, "slug": "wise", "label": "Wise", "receive_max": 9000}],
    )
    response = client.post("/api/monito/compare", json={"country": "MX", "amount": 500})
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["slug"] == "wise"
    assert data[0]["receive_max"] == 9000
    mock_inst.compare.assert_awaited_once()


def test_monito_compare_validation_country() -> None:
    response = client.post("/api/monito/compare", json={"country": "mex", "amount": 100})
    assert response.status_code == 422


def test_monito_compare_validation_amount() -> None:
    response = client.post("/api/monito/compare", json={"country": "mx", "amount": 0})
    assert response.status_code == 422


@patch("app.services.monito_playwright_service.MonitoPlaywrightService")
def test_monito_compare_value_error_is_400(mock_svc_class: object) -> None:
    mock_inst = mock_svc_class.return_value
    mock_inst.compare = AsyncMock(side_effect=ValueError("No default receive currency"))
    response = client.post("/api/monito/compare", json={"country": "zz", "amount": 100})
    assert response.status_code == 400
    assert response.json()["detail"]
