from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from scripts.cloudflare_gateway import GatewayConfig, GatewayError, load_config, sync_origin

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = "https://leadradar-gateway.example.workers.dev"
KEY = "unit-test-only-key-" * 3


def test_worker_routing_security_and_real_sqlite_idempotency():
    node = shutil.which("node")
    assert node, "Node.js is required to verify the deployed gateway"
    result = subprocess.run(
        [node, "--test", str(ROOT / "deploy/cloudflare-gateway/worker.test.mjs")],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_gateway_is_opt_in(tmp_path):
    assert load_config(tmp_path) is None


@pytest.mark.parametrize("public_url", ["http://a.b.workers.dev", "https://evil.test", "https://a.b.workers.dev/", "https://u:p@a.b.workers.dev", "https://a.b.workers.dev?q=x", 123])
def test_invalid_gateway_configuration_fails_without_leaking_the_key(tmp_path, public_url):
    runtime = tmp_path / ".runtime"
    runtime.mkdir()
    (runtime / "cloudflare-gateway.json").write_text(json.dumps({"public_url": public_url}))
    (runtime / "cloudflare-gateway.key").write_text(KEY)
    with pytest.raises(GatewayError) as error:
        load_config(tmp_path)
    assert KEY not in str(error.value)


def test_gateway_config_and_update_only_send_credentials_to_the_fixed_control_endpoint(tmp_path):
    runtime = tmp_path / ".runtime"
    runtime.mkdir()
    (runtime / "cloudflare-gateway.json").write_text(json.dumps({"public_url": PUBLIC}))
    (runtime / "cloudflare-gateway.key").write_text(KEY)
    config = load_config(tmp_path)
    assert config.host == "leadradar-gateway.example.workers.dev"
    calls = []

    def respond(request):
        calls.append(request)
        assert str(request.url) == PUBLIC + "/__leadradar_gateway__/origin"
        assert request.headers["Authorization"] == "Bearer " + KEY
        assert request.method == "PUT"
        assert json.loads(request.content) == {"origin": "https://unit.trycloudflare.com"}
        return httpx.Response(200, json={"ok": True, "changed": False})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        sync_origin(config, "https://unit.trycloudflare.com", client=client)
    assert len(calls) == 1


@pytest.mark.parametrize("status", [401, 503, 302])
def test_gateway_sync_never_replays_or_follows_redirects(status):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, json={"ok": False}, headers={"Location": "https://evil.test"})

    with httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=False) as client:
        with pytest.raises(GatewayError):
            sync_origin(GatewayConfig(PUBLIC, KEY), "https://unit.trycloudflare.com", client=client)
    assert len(calls) == 1


@pytest.mark.parametrize("origin", ["https://evil.test", "http://unit.trycloudflare.com", "https://unit.trycloudflare.com/path"])
def test_invalid_origin_does_not_make_any_request(origin):
    def forbidden(request):
        raise AssertionError("Unexpected outbound request")

    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        with pytest.raises(GatewayError):
            sync_origin(GatewayConfig(PUBLIC, KEY), origin, client=client)


@pytest.mark.parametrize("body", [b"[]", b"null", b"<html>offline</html>", b'{"ok":false}'])
def test_malformed_gateway_reply_fails_safely_without_replay(body):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, content=body)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(GatewayError) as error:
            sync_origin(GatewayConfig(PUBLIC, KEY), "https://unit.trycloudflare.com", client=client)
    assert len(calls) == 1
    assert KEY not in str(error.value)
