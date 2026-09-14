from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_systemd_service_uses_private_single_worker_runtime() -> None:
    service = (ROOT / "deployment/systemd/rivalmap.service").read_text()

    assert "User=rivalmap" in service
    assert "Group=rivalmap" in service
    assert "EnvironmentFile=/etc/rivalmap/rivalmap.env" in service
    assert "server:app --host 127.0.0.1 --port 8000 --workers 1" in service
    assert "Restart=on-failure" in service
    assert "StandardOutput=journal" in service


def test_nginx_preserves_sse_streaming_and_limits_run_starts() -> None:
    nginx = (ROOT / "deployment/nginx/rivalmap.conf").read_text()

    assert "limit_req_zone" in nginx
    for endpoint in ("/api/v1/runs/stream", "/api/runs/stream"):
        start = nginx.index(f"location = {endpoint}")
        end = nginx.index("\n    }", start)
        location = nginx[start:end]
        assert "limit_req zone=rivalmap_run_starts" in location
        assert "proxy_http_version 1.1" in location
        assert "proxy_buffering off" in location
        assert "proxy_request_buffering off" in location
        assert "proxy_cache off" in location
        assert "proxy_read_timeout 180s" in location
        assert "gzip off" in location
        assert 'X-Accel-Buffering "no"' in location


def test_deployment_environment_uses_iam_role_and_working_model() -> None:
    environment = (ROOT / "deployment/rivalmap.env.example").read_text()

    assert "RIVALMAP_AWS_REGION=us-west-2" in environment
    assert (
        "RIVALMAP_BEDROCK_MODEL_ID="
        "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    ) in environment
    assert "EXA_API_KEY=replace-with-production-exa-key" in environment
    assert "AWS_ACCESS_KEY_ID=" not in environment
    assert "AWS_SECRET_ACCESS_KEY=" not in environment
