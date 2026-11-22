"""Unit tests for Fernet credential encryption and LineChannelAdapter."""

import base64
import hashlib
import hmac
import json

import httpx
import pytest

from app.channels.base import ChannelAPIError, ReplyTokenExpiredError
from app.channels.line import LineChannelAdapter, parse_line_events, verify_line_signature
from app.core.crypto import (
    CredentialCryptoError,
    decrypt_credentials,
    encrypt_credentials,
    generate_fernet_key,
)


def _sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def test_fernet_credential_encryption_round_trip_and_wrong_key_error() -> None:
    key_a = generate_fernet_key()
    key_b = generate_fernet_key()
    creds = {"channel_access_token": "line-secret-token-123"}

    encrypted = encrypt_credentials(creds, fernet_key=key_a)
    assert "line-secret-token-123" not in encrypted
    assert decrypt_credentials(encrypted, fernet_key=key_a) == creds

    with pytest.raises(CredentialCryptoError, match="Failed to decrypt"):
        decrypt_credentials(encrypted, fernet_key=key_b)


def test_line_signature_verification_accepts_valid_and_rejects_tampered() -> None:
    secret = "my-line-channel-secret"
    body = b'{"events":[]}'
    valid_sig = _sign(body, secret)

    assert verify_line_signature(body, valid_sig, secret) is True
    assert verify_line_signature(body, "invalid-signature", secret) is False
    assert verify_line_signature(body + b" ", valid_sig, secret) is False
    assert verify_line_signature(body, "", secret) is False


def test_parse_line_events_handles_text_image_sticker_and_ignores_follow() -> None:
    payload: dict[str, object] = {
        "events": [
            {
                "type": "follow",
                "webhookEventId": "evt-follow",
                "source": {"type": "user", "userId": "U1"},
            },
            {
                "type": "message",
                "webhookEventId": "evt-text",
                "replyToken": "rt-1",
                "timestamp": 1700000001000,
                "source": {"type": "user", "userId": "U1"},
                "message": {"id": "m1", "type": "text", "text": "ค่าส่งกี่บาทคะ"},
            },
            {
                "type": "message",
                "webhookEventId": "evt-img",
                "replyToken": "rt-2",
                "timestamp": 1700000002000,
                "source": {"type": "user", "userId": "U2"},
                "message": {"id": "m2", "type": "image"},
            },
            {
                "type": "message",
                "webhookEventId": "evt-stk",
                "replyToken": "rt-3",
                "timestamp": 1700000003000,
                "source": {"type": "user", "userId": "U3"},
                "message": {"id": "m3", "type": "sticker", "packageId": "1", "stickerId": "1"},
            },
        ]
    }

    events = parse_line_events(payload)

    assert len(events) == 3
    assert events[0].event_id == "evt-text"
    assert events[0].message_type == "text"
    assert events[0].text == "ค่าส่งกี่บาทคะ"
    assert events[1].message_type == "image"
    assert events[2].message_type == "sticker"


async def test_line_adapter_reply_push_profile_loading_and_expired_token() -> None:
    recorded: list[tuple[str, str, dict[str, object] | None]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else None
        recorded.append((request.method, request.url.path, body))
        if request.url.path == "/v2/bot/message/reply":
            if body and body.get("replyToken") == "expired-rt":
                return httpx.Response(400, json={"message": "Invalid reply token"})
            return httpx.Response(200, json={})
        if request.url.path == "/v2/bot/message/push":
            if body and body.get("to") == "U_FAIL":
                return httpx.Response(500, json={"message": "internal error"})
            return httpx.Response(200, json={})
        if request.url.path == "/v2/bot/profile/U123":
            return httpx.Response(200, json={"userId": "U123", "displayName": "คุณสมศรี"})
        if request.url.path == "/v2/bot/chat/loading/start":
            return httpx.Response(202, json={})
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        adapter = LineChannelAdapter(channel_access_token="tok-abc", http_client=client)

        await adapter.send_reply("valid-rt", "ค่าส่ง 40 บาทค่ะ")
        with pytest.raises(ReplyTokenExpiredError):
            await adapter.send_reply("expired-rt", "สวัสดีค่ะ")

        await adapter.send_push("U123", "ส่งผ่าน Push API ค่ะ")
        with pytest.raises(ChannelAPIError):
            await adapter.send_push("U_FAIL", "error test")

        profile = await adapter.get_profile("U123")
        assert profile.display_name == "คุณสมศรี"

        await adapter.show_loading("U123", seconds=20)

    paths = [path for _, path, _ in recorded]
    assert "/v2/bot/message/reply" in paths
    assert "/v2/bot/message/push" in paths
    assert "/v2/bot/profile/U123" in paths
    assert "/v2/bot/chat/loading/start" in paths
