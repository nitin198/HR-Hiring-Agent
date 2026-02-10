"""Microsoft Graph API client for Outlook access."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any
import asyncio

import httpx
import msal

from src.config.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class GraphToken:
    """Cached Graph access token."""

    access_token: str
    expires_at: datetime

    def is_valid(self) -> bool:
        """Return True if the token is still valid."""
        return datetime.now(timezone.utc) < self.expires_at


class DeviceCodeRequiredError(RuntimeError):
    """Device code login is required."""


class DeviceCodePendingError(RuntimeError):
    """Device code login is in progress."""


class GraphClient:
    """Minimal Microsoft Graph API client."""

    _shared_token: GraphToken | None = None
    _device_flow_message: str | None = None
    _device_flow_in_progress: bool = False
    _device_flow_error: str | None = None

    def __init__(self) -> None:
        get_settings.cache_clear()
        settings = get_settings()
        self._auth_mode = settings.outlook_auth_mode
        self._tenant_id = settings.outlook_tenant_id
        self._client_id = settings.outlook_client_id
        self._client_secret = settings.outlook_client_secret
        self._device_scopes = settings.outlook_device_scopes
        self._base_url = "https://graph.microsoft.com/v1.0"
        self._token: GraphToken | None = None

    async def _get_access_token(self) -> str:
        """Fetch or reuse an access token."""
        shared = GraphClient._shared_token
        if shared and shared.is_valid():
            self._token = shared
            return shared.access_token
        if self._token and self._token.is_valid():
            GraphClient._shared_token = self._token
            return self._token.access_token

        if not self._tenant_id or not self._client_id:
            raise ValueError("Outlook Graph credentials are not configured.")

        if self._auth_mode == "client_credentials":
            if not self._client_secret:
                raise ValueError("OUTLOOK_CLIENT_SECRET is required for client_credentials auth.")
            return await self._get_client_credentials_token()
        if self._auth_mode == "device_code":
            if GraphClient._device_flow_in_progress:
                raise DeviceCodePendingError("Device code login pending.")
            raise DeviceCodeRequiredError("Device code login required.")

        raise ValueError(f"Unsupported Outlook auth mode: {self._auth_mode}")

    async def _get_client_credentials_token(self) -> str:
        authority = f"https://login.microsoftonline.com/{self._tenant_id}"
        app = msal.ConfidentialClientApplication(
            self._client_id,
            authority=authority,
            client_credential=self._client_secret,
        )

        def _acquire() -> dict[str, Any]:
            return app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])

        result = await asyncio.to_thread(_acquire)
        if "access_token" not in result:
            raise ValueError(f"Failed to acquire token: {result.get('error_description') or result}")

        access_token = result["access_token"]
        expires_in = int(result.get("expires_in", 3599))
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)
        self._token = GraphToken(access_token=access_token, expires_at=expires_at)
        return access_token

    async def _get_device_code_token(self) -> str:
        authority = f"https://login.microsoftonline.com/{self._tenant_id}"
        app = msal.PublicClientApplication(self._client_id, authority=authority)

        def _start_flow() -> dict[str, Any]:
            return app.initiate_device_flow(scopes=self._device_scopes)

        device_flow = await asyncio.to_thread(_start_flow)
        if "user_code" not in device_flow:
            raise ValueError(f"Failed to start device flow: {device_flow}")

        logger.info("Device code login: %s", device_flow.get("message"))

        def _acquire() -> dict[str, Any]:
            return app.acquire_token_by_device_flow(device_flow)

        result = await asyncio.to_thread(_acquire)
        if "access_token" not in result:
            raise ValueError(f"Failed to acquire token: {result.get('error_description') or result}")

        access_token = result["access_token"]
        expires_in = int(result.get("expires_in", 3599))
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)
        self._token = GraphToken(access_token=access_token, expires_at=expires_at)
        GraphClient._shared_token = self._token
        return access_token

    @classmethod
    async def start_device_flow(cls, tenant_id: str, client_id: str, scopes: list[str]) -> str:
        """Start device code flow and return the login message."""
        if cls._device_flow_in_progress and cls._device_flow_message:
            return cls._device_flow_message

        authority = f"https://login.microsoftonline.com/{tenant_id}"
        app = msal.PublicClientApplication(client_id, authority=authority)

        def _start_flow() -> dict[str, Any]:
            return app.initiate_device_flow(scopes=scopes)

        device_flow = await asyncio.to_thread(_start_flow)
        if "user_code" not in device_flow:
            raise ValueError(f"Failed to start device flow: {device_flow}")

        cls._device_flow_message = device_flow.get("message")
        cls._device_flow_in_progress = True
        cls._device_flow_error = None

        async def _complete() -> None:
            def _acquire() -> dict[str, Any]:
                return app.acquire_token_by_device_flow(device_flow)

            try:
                result = await asyncio.to_thread(_acquire)
                if "access_token" not in result:
                    cls._device_flow_error = result.get("error_description") or str(result)
                    return
                access_token = result["access_token"]
                expires_in = int(result.get("expires_in", 3599))
                expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)
                cls._shared_token = GraphToken(access_token=access_token, expires_at=expires_at)
            finally:
                cls._device_flow_in_progress = False

        asyncio.create_task(_complete())
        return cls._device_flow_message or "Complete device code login."

    @classmethod
    def get_device_flow_message(cls) -> str | None:
        """Return the latest device code login message."""
        return cls._device_flow_message

    @classmethod
    def has_valid_token(cls) -> bool:
        """Return True if a shared token exists and is valid."""
        return cls._shared_token is not None and cls._shared_token.is_valid()

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Send an authenticated request to Microsoft Graph."""
        token = await self._get_access_token()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        headers.setdefault("Accept", "application/json")
        if "json" in kwargs:
            headers.setdefault("Content-Type", "application/json")

        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()
            return response
