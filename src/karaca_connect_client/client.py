"""Pre-release client adapted from the existing public integration's API shape.

No Karaca credentials or requests have been used to live-test this code.
Endpoint paths are reverse-engineered / undocumented and may change.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .exceptions import (
    KaracaApiError,
    KaracaAuthError,
    KaracaConnectionError,
    KaracaDeviceNotFound,
    KaracaRateLimitError,
    KaracaServiceError,
)

DEFAULT_BASE_URL = "https://karacaconnectapi.krc.com.tr"


class KaracaClient:
    """Asynchronous cloud client. The caller owns the aiohttp session."""

    def __init__(
        self,
        session: ClientSession,
        *,
        email: str,
        password: str,
        device_id: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 20.0,
    ) -> None:
        if not email or not password:
            raise ValueError("Email and password must be provided")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self._session = session
        self._email = email
        self._password = password
        self._device_id = str(device_id) if device_id else None
        self._base_url = base_url.rstrip("/")
        self._timeout = ClientTimeout(total=timeout_seconds)
        self._token: str | None = None
        self._auth_lock = asyncio.Lock()

    @property
    def device_id(self) -> str | None:
        return self._device_id

    async def _send(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
        token: str | None = None,
    ) -> tuple[int, Mapping[str, Any]]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "KaracaConnectClient/0.1.0a1",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            async with self._session.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                json=dict(payload) if payload is not None else None,
                timeout=self._timeout,
            ) as response:
                status = response.status
                try:
                    data = await response.json(content_type=None)
                except (ValueError, ClientError, TypeError) as exc:
                    # Error pages can be HTML or empty: retain the HTTP status
                    # so callers can distinguish auth, throttling and outages.
                    if status >= 400:
                        data = {}
                    else:
                        raise KaracaConnectionError("Invalid cloud API response") from exc
        except (ClientError, TimeoutError, asyncio.TimeoutError) as exc:
            raise KaracaConnectionError("Unable to reach Karaca cloud service") from exc
        if not isinstance(data, Mapping):
            if status >= 400:
                data = {}
            else:
                raise KaracaConnectionError("Unexpected cloud API response type")
        return status, data

    @staticmethod
    def _check(status: int, data: Mapping[str, Any]) -> None:
        if status in (401, 403):
            raise KaracaAuthError("Karaca authentication or authorization failed")
        if status == 429:
            raise KaracaRateLimitError("Karaca cloud rate limit reached")
        if status >= 500:
            raise KaracaServiceError("Karaca cloud service unavailable")
        if not 200 <= status < 300 or data.get("succeeded") is False:
            raise KaracaApiError("Karaca cloud request rejected")

    async def login(self, *, force: bool = False) -> None:
        async with self._auth_lock:
            if self._token and not force:
                return
            status, data = await self._send(
                "POST",
                "/api/auth/signin",
                payload={"email": self._email, "password": self._password},
            )
            # A service outage / throttle must not become "invalid password".
            if status in (401, 403) or (
                200 <= status < 300 and data.get("succeeded") is False
            ):
                raise KaracaAuthError("Karaca credentials were rejected")
            self._check(status, data)
            payload = data.get("data")
            token = payload.get("jwToken") if isinstance(payload, Mapping) else None
            if not isinstance(token, str) or not token:
                raise KaracaAuthError("Cloud response did not include a token")
            self._token = token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        await self.login()
        token = self._token
        status, data = await self._send(method, path, payload=payload, token=token)
        if status == 401:
            # Another coroutine may already have refreshed the expired token.
            if self._token == token:
                self._token = None
            await self.login()
            status, data = await self._send(
                method, path, payload=payload, token=self._token
            )
        self._check(status, data)
        return data

    async def get_devices(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/api/v1/devices/me")
        devices = data.get("data")
        if not isinstance(devices, list) or not all(isinstance(d, dict) for d in devices):
            raise KaracaConnectionError("Malformed device list")
        return devices

    async def resolve_device_id(self) -> str:
        if self._device_id:
            return self._device_id
        devices = await self.get_devices()
        # Never guess which device to control from a multi-device account.
        # The Home Assistant config flow selects and stores a device explicitly.
        if len(devices) != 1 or not devices[0].get("id"):
            raise KaracaDeviceNotFound(
                "Select a device ID explicitly; automatic selection requires exactly one device"
            )
        self._device_id = str(devices[0]["id"])
        return self._device_id

    async def get_detail(self) -> dict[str, Any]:
        device_id = await self.resolve_device_id()
        response = await self._request("GET", f"/api/v1/devices/{device_id}")
        data = response.get("data")
        if not isinstance(data, dict):
            raise KaracaConnectionError("Malformed device detail response")
        return data

    async def get_settings(self) -> list[dict[str, Any]]:
        device_id = await self.resolve_device_id()
        response = await self._request("GET", f"/api/v1/devices/{device_id}/settings")
        data = response.get("data")
        settings = data.get("notifications") if isinstance(data, dict) else None
        if not isinstance(settings, list):
            raise KaracaConnectionError("Malformed settings response")
        return settings

    async def set_mode(self, mode_id: int, active: bool = True) -> None:
        device_id = await self.resolve_device_id()
        await self._request(
            "PUT", f"/api/v1/devices/{device_id}/modes/{mode_id}",
            payload={"active": active},
        )

    async def set_setting(self, setting_id: int, value: bool) -> None:
        device_id = await self.resolve_device_id()
        path = f"/api/v1/devices/{device_id}/settings/{setting_id}"
        try:
            await self._request("PUT", path, payload={"value": value})
        except KaracaApiError:
            # Existing integration uses this fallback; compatibility must be
            # confirmed against the live API before any public release.
            await self._request("PUT", path, payload={"active": value})
