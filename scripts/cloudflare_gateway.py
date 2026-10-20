"""Local configuration and authenticated route update; never logs credentials."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx


class GatewayError(RuntimeError):
    pass


@dataclass(frozen=True)
class GatewayConfig:
    public_url: str
    update_key: str

    @property
    def host(self) -> str:
        return urlsplit(self.public_url).hostname or ""


def load_config(root: Path) -> GatewayConfig | None:
    path = root / ".runtime/cloudflare-gateway.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        public_url = data["public_url"]
        key = (root / ".runtime/cloudflare-gateway.key").read_text(encoding="utf-8").strip()
        if not re.fullmatch(r"https://[a-z0-9-]+\.[a-z0-9-]+\.workers\.dev", public_url):
            raise ValueError
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", key):
            raise ValueError
    except (OSError, ValueError, TypeError, KeyError):
        raise GatewayError("Invalid local gateway configuration or missing update key") from None
    return GatewayConfig(public_url=public_url, update_key=key)


def sync_origin(config: GatewayConfig, origin: str, *, client: httpx.Client | None = None) -> None:
    if not re.fullmatch(r"https://[a-z0-9-]+\.trycloudflare\.com", origin):
        raise GatewayError("Invalid Cloudflare tunnel origin")
    owned = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=False)
    try:
        response = client.put(
            config.public_url + "/__leadradar_gateway__/origin",
            headers={"Authorization": "Bearer " + config.update_key}, json={"origin": origin},
        )
        payload = response.json() if response.status_code == 200 else None
        if response.status_code != 200 or not isinstance(payload, dict) or payload.get("ok") is not True:
            raise GatewayError(f"Gateway route update failed (HTTP {response.status_code})")
    except (httpx.HTTPError, ValueError):
        raise GatewayError("Gateway route update unavailable; no request was replayed") from None
    finally:
        if owned:
            client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["config", "sync"])
    parser.add_argument("--origin", default="")
    args = parser.parse_args()
    try:
        config = load_config(Path(__file__).resolve().parents[1])
        if args.operation == "config":
            print(json.dumps({"public_url": config.public_url, "host": config.host} if config else None))
        elif config:
            sync_origin(config, args.origin)
            print("Gateway route synchronized.")
        else:
            raise GatewayError("Gateway is not configured")
    except GatewayError as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()
