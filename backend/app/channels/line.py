"""LINE Messaging API ChannelAdapter implementation using async httpx."""

import base64
import hashlib
import hmac
from typing import cast

import httpx

from app.channels.base import (
    ChannelAPIError,
    InboundEvent,
    MessageType,
    ReplyTokenExpiredError,
    UserProfile,
)
from app.core.logging import get_logger

LINE_API_BASE_URL = "https://api.line.me"
LINE_MAX_TEXT_LENGTH = 5000

logger = get_logger("app.channels.line")


def verify_line_signature(body: bytes, signature: str, secret: str) -> bool:
    """Verify LINE X-Line-Signature header via constant-time HMAC-SHA256."""
    if not secret or not signature:
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, signature.strip())


def parse_line_events(payload: dict[str, object]) -> list[InboundEvent]:
    """Parse LINE Messaging API webhook payload into normalized InboundEvent list."""
    raw_events = payload.get("events")
    if not isinstance(raw_events, list):
        return []

    parsed: list[InboundEvent] = []
    for raw in raw_events:
        if not isinstance(raw, dict) or raw.get("type") != "message":
            continue
        source = raw.get("source")
        message = raw.get("message")
        if not isinstance(source, dict) or not isinstance(message, dict):
            continue

        user_id = source.get("userId")
        if not isinstance(user_id, str) or not user_id.strip():
            continue

        raw_event_id = raw.get("webhookEventId") or message.get("id")
        if not isinstance(raw_event_id, str) or not raw_event_id.strip():
            continue

        raw_msg_type = str(message.get("type", ""))
        msg_type: MessageType
        text_content: str | None = None
        if raw_msg_type == "text":
            msg_type = "text"
            raw_text = message.get("text")
            text_content = str(raw_text) if raw_text is not None else ""
        elif raw_msg_type == "image":
            msg_type = "image"
        elif raw_msg_type == "sticker":
            msg_type = "sticker"
        else:
            msg_type = "unsupported"

        reply_token_raw = raw.get("replyToken")
        reply_token = str(reply_token_raw) if isinstance(reply_token_raw, str) else None
        ts_raw = raw.get("timestamp", 0)
        timestamp_ms = int(ts_raw) if isinstance(ts_raw, (int, float)) else 0

        parsed.append(
            InboundEvent(
                event_id=raw_event_id,
                external_user_id=user_id,
                message_type=msg_type,
                text=text_content,
                reply_token=reply_token,
                timestamp_ms=timestamp_ms,
            )
        )
    return parsed


class LineChannelAdapter:
    """Async LINE Messaging API client implementing ChannelAdapter."""

    def __init__(
        self,
        *,
        channel_access_token: str,
        http_client: httpx.AsyncClient | None = None,
        api_base_url: str = LINE_API_BASE_URL,
    ) -> None:
        self._access_token = channel_access_token
        self._http_client = http_client
        self._api_base_url = api_base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    def verify_signature(self, body: bytes, signature: str, secret: str) -> bool:
        return verify_line_signature(body, signature, secret)

    def parse_events(self, payload: dict[str, object]) -> list[InboundEvent]:
        return parse_line_events(payload)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, object] | None = None,
    ) -> httpx.Response:
        url = f"{self._api_base_url}{path}"
        if self._http_client is not None:
            return await self._http_client.request(
                method,
                url,
                headers=self._headers(),
                json=json_body,
            )
        async with httpx.AsyncClient(timeout=10.0) as client:
            return await client.request(
                method,
                url,
                headers=self._headers(),
                json=json_body,
            )

    async def send_reply(self, reply_token: str, text: str) -> None:
        payload: dict[str, object] = {
            "replyToken": reply_token,
            "messages": [{"type": "text", "text": text[:LINE_MAX_TEXT_LENGTH]}],
        }
        resp = await self._request("POST", "/v2/bot/message/reply", json_body=payload)
        if resp.status_code == 200:
            return
        body_lower = resp.text.lower()
        if resp.status_code == 400 and "reply token" in body_lower:
            raise ReplyTokenExpiredError(f"LINE reply token rejected: {resp.text}")
        raise ChannelAPIError(f"LINE reply API failed ({resp.status_code}): {resp.text}")

    async def send_push(self, external_user_id: str, text: str) -> None:
        payload: dict[str, object] = {
            "to": external_user_id,
            "messages": [{"type": "text", "text": text[:LINE_MAX_TEXT_LENGTH]}],
        }
        resp = await self._request("POST", "/v2/bot/message/push", json_body=payload)
        if resp.status_code != 200:
            raise ChannelAPIError(f"LINE push API failed ({resp.status_code}): {resp.text}")

    async def get_profile(self, external_user_id: str) -> UserProfile:
        try:
            resp = await self._request("GET", f"/v2/bot/profile/{external_user_id}")
            if resp.status_code == 200:
                data = cast(dict[str, object], resp.json())
                name_raw = data.get("displayName")
                name = str(name_raw) if isinstance(name_raw, str) and name_raw.strip() else None
                return UserProfile(external_user_id=external_user_id, display_name=name)
        except Exception as exc:
            logger.warning("line_profile_fetch_failed", user_id=external_user_id, error=str(exc))
        return UserProfile(external_user_id=external_user_id, display_name=None)

    async def show_loading(self, external_user_id: str, seconds: int = 20) -> None:
        clamped = max(5, min(60, (seconds // 5) * 5))
        payload: dict[str, object] = {"chatId": external_user_id, "loadingSeconds": clamped}
        try:
            resp = await self._request("POST", "/v2/bot/chat/loading/start", json_body=payload)
            if resp.status_code >= 400:
                logger.warning(
                    "line_loading_indicator_rejected",
                    status_code=resp.status_code,
                    user_id=external_user_id,
                )
        except Exception as exc:
            logger.warning(
                "line_loading_indicator_failed",
                user_id=external_user_id,
                error=str(exc),
            )
