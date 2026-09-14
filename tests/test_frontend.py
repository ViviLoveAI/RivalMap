from fastapi.testclient import TestClient

from server import app


def test_frontend_and_module_assets_are_served_without_starting_providers():
    client = TestClient(app)

    page = client.get("/")
    state_module = client.get("/assets/state.js")
    app_module = client.get("/assets/app.js")
    export_module = client.get("/assets/export.js")

    assert page.status_code == 200
    assert "Agent activity" in page.text
    assert "User-centered RivalMap" in page.text
    assert "Your closest competitive space" in page.text
    assert "Market framing" in page.text
    assert state_module.status_code == 200
    assert "applyVisualizationDelta" in state_module.text
    assert app_module.status_code == 200
    assert 'fetch("/api/v1/runs/stream"' in app_module.text
    assert export_module.status_code == 200
    assert "buildPresentationSvg" in export_module.text
    assert "image/png" in app_module.text
    assert "presentation-mode" in page.text
    assert "comparisonModel" in state_module.text
    assert "prefers-reduced-motion" in client.get("/assets/styles.css").text
