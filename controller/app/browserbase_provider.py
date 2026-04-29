"""Browserbase managed-browser provider.

Browserbase (https://www.browserbase.com) is a managed Chromium-as-a-service
that ships with built-in fingerprint randomization, residential proxies and
anti-bot evasion — useful when sites like HeyGen detect data-center IPs and
serve a degraded UI to ordinary headed Chromium.

When `USE_BROWSERBASE=true`, the controller asks Browserbase for a fresh
session per local session, gets back a CDP `connectUrl`, and attaches via
`playwright.chromium.connect_over_cdp(...)`. The rest of the manager
machinery (auth profiles, isolation, observe/actions) keeps working
unchanged because it operates on the Playwright `Browser`/`BrowserContext`,
not on how the browser was launched.

This module is a thin HTTP wrapper. Lifecycle:
- `create_session()` → `{id, connectUrl, ...}`. Costs Browserbase credits;
  every local session creation triggers one.
- `release_session(id)` → best-effort cleanup so we don't keep paid
  sessions running after the operator closes them. Browserbase auto-times
  out idle sessions but explicit release is courteous and faster.

Tunables via env vars (see config.py):
- BROWSERBASE_API_KEY         — required
- BROWSERBASE_PROJECT_ID      — required
- BROWSERBASE_REGION          — eu-central-1 (default), us-east-1, us-west-2, ap-southeast-1
- BROWSERBASE_PROXY_COUNTRY   — ISO country code for residential proxy (e.g. IT). Empty = no proxy.
- BROWSERBASE_KEEP_ALIVE      — keep session alive after disconnect (paid plans only)
- BROWSERBASE_TIMEOUT_SECONDS — request timeout for Browserbase API calls
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

BROWSERBASE_API_BASE = "https://api.browserbase.com/v1"


class BrowserbaseError(RuntimeError):
    pass


class BrowserbaseProvider:
    def __init__(
        self,
        *,
        api_key: str,
        project_id: str,
        region: str = "eu-central-1",
        proxy_country: str = "",
        keep_alive: bool = False,
        timeout_seconds: float = 20.0,
    ) -> None:
        if not api_key:
            raise ValueError("BROWSERBASE_API_KEY required")
        if not project_id:
            raise ValueError("BROWSERBASE_PROJECT_ID required")
        self.api_key = api_key
        self.project_id = project_id
        self.region = region
        self.proxy_country = proxy_country.strip().upper()
        self.keep_alive = keep_alive
        self._http = httpx.AsyncClient(
            base_url=BROWSERBASE_API_BASE,
            headers={
                "x-bb-api-key": api_key,
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(timeout_seconds, connect=5.0),
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def create_session(
        self,
        *,
        user_agent: Optional[str] = None,
        locale: str = "it-IT",
        timezone: str = "Europe/Rome",
        viewport_width: int = 1920,
        viewport_height: int = 1080,
    ) -> dict[str, Any]:
        """Spin up a new Browserbase session. Returns the response payload
        which contains `id` and `connectUrl` (Playwright-compatible CDP URL).

        Raises BrowserbaseError on any non-2xx response so the caller can
        decide to fall back to local Chromium.
        """
        body: dict[str, Any] = {
            "projectId": self.project_id,
            "browserSettings": {
                # Fingerprint config — Browserbase rotates the underlying
                # Chrome version + plugin set + canvas noise to look like a
                # real user. We constrain to Italian desktop Windows so the
                # signals stay coherent with what HeyGen expects from a
                # human Italian operator.
                "fingerprint": {
                    "browsers": ["chrome"],
                    "devices": ["desktop"],
                    "locales": [locale],
                    "operatingSystems": ["windows"],
                    "screen": {
                        "minWidth": viewport_width,
                        "maxWidth": viewport_width,
                        "minHeight": viewport_height,
                        "maxHeight": viewport_height,
                    },
                },
                "viewport": {
                    "width": viewport_width,
                    "height": viewport_height,
                },
                # We want the session to look "live" to the target site —
                # Browserbase emits human-like cursor/timing patterns when
                # this is enabled. Ignored on free tier.
                "solveCaptchas": False,
            },
            "region": self.region,
            "keepAlive": bool(self.keep_alive),
        }

        if user_agent:
            # Note: forcing a UA usually CONFLICTS with the fingerprint
            # randomization above. We only set it if the operator
            # explicitly opted in.
            body["browserSettings"]["userAgent"] = user_agent

        if self.proxy_country:
            # Residential proxies cost extra and aren't on every plan.
            # When empty country is configured we omit the proxy block
            # entirely so plans without proxies don't 4xx.
            body["proxies"] = [
                {
                    "type": "browserbase",
                    "geolocation": {"country": self.proxy_country},
                }
            ]

        try:
            resp = await self._http.post("/sessions", json=body)
        except httpx.HTTPError as e:
            raise BrowserbaseError(f"network error creating session: {e}") from e

        if resp.status_code == 401:
            raise BrowserbaseError("Browserbase 401 — invalid BROWSERBASE_API_KEY")
        if resp.status_code == 403:
            raise BrowserbaseError("Browserbase 403 — project access denied; verify BROWSERBASE_PROJECT_ID")
        if resp.status_code == 429:
            raise BrowserbaseError("Browserbase 429 — rate limit / concurrent session quota exceeded")
        if not resp.is_success:
            try:
                detail = resp.json()
            except ValueError:
                detail = resp.text[:200]
            raise BrowserbaseError(f"Browserbase {resp.status_code}: {detail}")

        data = resp.json()
        if not data.get("id") or not data.get("connectUrl"):
            raise BrowserbaseError(f"Browserbase response missing id/connectUrl: {data}")
        logger.info(
            "browserbase session %s created (region=%s proxy=%s)",
            data["id"], self.region, self.proxy_country or "off",
        )
        return data

    async def release_session(self, session_id: str) -> None:
        """Best-effort release. Browserbase will auto-timeout idle sessions
        anyway, but explicit release frees the slot faster (matters on
        small-concurrency plans)."""
        if not session_id:
            return
        try:
            await self._http.post(
                f"/sessions/{session_id}",
                json={"projectId": self.project_id, "status": "REQUEST_RELEASE"},
            )
        except Exception as e:  # noqa: BLE001 — best-effort cleanup
            logger.debug("browserbase release_session %s ignored: %s", session_id, e)
