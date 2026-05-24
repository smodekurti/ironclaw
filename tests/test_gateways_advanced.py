import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ironclaw.gateway.base import OutboundMessage, Platform, PlatformID, InboundMessage
from ironclaw.gateway.session import GatewaySession, SessionStore
from ironclaw.gateway.telegram import TelegramGateway
from ironclaw.gateway.whatsapp import WhatsAppGateway
from ironclaw.gateway.imessage import iMessageGateway

# === session.py tests ===

def test_session_store_in_memory():
    store = SessionStore(default_agent_id="test_agent")
    pid = PlatformID(Platform.TELEGRAM, "user1")
    
    session = store.get_or_create(pid)
    assert session.agent_id == "test_agent"
    assert session.platform_id == pid
    assert store.active_count() == 1
    
    session.touch()
    assert session.message_count == 1
    
    # get existing
    session2 = store.get_or_create(pid)
    assert session2 is session
    
    # get
    assert store.get(pid) is session
    assert store.get(PlatformID(Platform.TELEGRAM, "user2")) is None
    
    # update agent
    store.update_agent(pid, "new_agent")
    assert store.get(pid).agent_id == "new_agent"
    
    assert len(store.all_sessions()) == 1

def test_session_store_sqlite(tmp_path):
    db_path = tmp_path / "sessions.db"
    store = SessionStore(default_agent_id="test_agent", db_path=db_path)
    pid = PlatformID(Platform.TELEGRAM, "user1")
    
    session = store.get_or_create(pid)
    session.touch()
    session.touch()
    store._persist(session)
    
    # Re-instantiate to test loading
    store2 = SessionStore(default_agent_id="other_agent", db_path=db_path)
    assert store2.active_count() == 1
    loaded = store2.get(pid)
    assert loaded is not None
    assert loaded.message_count == 2
    assert loaded.agent_id == "test_agent"

# === telegram.py tests ===

@pytest.fixture
def telegram_gw():
    return TelegramGateway(token="fake_token", webhook_url="https://fake.com")

@pytest.mark.asyncio
async def test_telegram_lifecycle(telegram_gw):
    with patch.object(telegram_gw, "_register_webhook", new_callable=AsyncMock) as mock_reg:
        await telegram_gw.start()
        mock_reg.assert_called_once()
        assert telegram_gw._client is not None
        
        await telegram_gw.stop()
        # Ensure client is closed or no longer running
        assert not telegram_gw._running

@pytest.mark.asyncio
async def test_telegram_send():
    gw = TelegramGateway(token="fake_token")
    await gw.start()
    
    resp_mock = MagicMock()
    resp_mock.json.return_value = {"ok": True}
    mock_post = AsyncMock(return_value=resp_mock)
    gw._client.post = mock_post
    
    out = OutboundMessage(
        platform_id=PlatformID(Platform.TELEGRAM, "12345"),
        text="Hello _world_",
    )
    await gw.send(out)
    
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert "sendMessage" in args[0]
    payload = kwargs["json"]
    assert payload["chat_id"] == "12345"
    assert "MarkdownV2" in payload["parse_mode"]
    
    await gw.stop()

@pytest.mark.asyncio
async def test_telegram_send_fallback():
    gw = TelegramGateway(token="fake_token")
    await gw.start()
    
    resp_mock_1 = MagicMock()
    resp_mock_1.json.return_value = {"ok": False, "description": "can't parse entities"}
    resp_mock_2 = MagicMock()
    resp_mock_2.json.return_value = {"ok": True}
    mock_post = AsyncMock(side_effect=[resp_mock_1, resp_mock_2])
    gw._client.post = mock_post
    
    out = OutboundMessage(
        platform_id=PlatformID(Platform.TELEGRAM, "12345"),
        text="Hello [world",
    )
    await gw.send(out)
    
    assert mock_post.call_count == 2
    # Second call shouldn't have parse_mode
    args, kwargs = mock_post.call_args
    assert "parse_mode" not in kwargs["json"]
    
    await gw.stop()

@pytest.mark.asyncio
async def test_telegram_webhook():
    gw = TelegramGateway(token="fake_token", allowed_chat_ids={123})
    
    dispatched = []
    gw.dispatch = AsyncMock(side_effect=lambda msg: dispatched.append(msg))
    
    update = {
        "update_id": 1,
        "message": {
            "message_id": 10,
            "chat": {"id": 123},
            "text": "Hello bot"
        }
    }
    await gw.handle_webhook(update)
    assert len(dispatched) == 1
    assert dispatched[0].text == "Hello bot"
    assert dispatched[0].platform_id.sender_id == "123"

    # Not allowed
    update2 = {
        "update_id": 2,
        "message": {
            "message_id": 11,
            "chat": {"id": 999},
            "text": "Hello bot"
        }
    }
    await gw.handle_webhook(update2)
    assert len(dispatched) == 1

@pytest.mark.asyncio
async def test_telegram_polling():
    gw = TelegramGateway(token="fake_token")
    gw._client = MagicMock()
    
    async def fake_call(*args, **kwargs):
        gw._running = False
        return {
            "result": [
                {"update_id": 100, "message": {"message_id": 1, "chat": {"id": 123}, "text": "Hi"}}
            ]
        }
    mock_call = AsyncMock(side_effect=fake_call)
    gw._call = mock_call
    
    dispatched = []
    gw.dispatch = AsyncMock(side_effect=lambda msg: dispatched.append(msg))
    
    gw._running = True
    
    async def fake_poll_loop():
        await gw._poll_loop()
        
    task = asyncio.create_task(fake_poll_loop())
    
    # Give the poll loop time to hit the _call mock
    await asyncio.sleep(0.01)
    
    # Cancel / stop the loop
    gw._running = False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
        
    assert mock_call.call_count >= 1
    assert len(dispatched) >= 1
    assert dispatched[0].text == "Hi"

# === whatsapp.py tests ===

@pytest.mark.asyncio
async def test_whatsapp_lifecycle():
    gw = WhatsAppGateway("token", "phone123", "verify_me")
    await gw.start()
    assert gw._client is not None
    await gw.stop()
    assert not gw._running

def test_whatsapp_verify_webhook():
    gw = WhatsAppGateway("token", "phone123", "verify_me")
    assert gw.verify_webhook("subscribe", "verify_me", "challenge123") == "challenge123"
    assert gw.verify_webhook("subscribe", "wrong", "challenge123") is None

def test_whatsapp_verify_signature():
    gw = WhatsAppGateway("token", "phone", "verify", app_secret="secret")
    body = b'{"test":"body"}'
    import hmac, hashlib
    expected_sig = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert gw.verify_signature(body, expected_sig) is True
    assert gw.verify_signature(body, "sha256=wrong") is False

@pytest.mark.asyncio
async def test_whatsapp_handle_webhook():
    gw = WhatsAppGateway("token", "phone", "verify", allowed_numbers={"+1234567890"})
    
    dispatched = []
    gw.dispatch = AsyncMock(side_effect=lambda msg: dispatched.append(msg))
    
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "+1234567890",
                        "id": "wamid123",
                        "type": "text",
                        "text": {"body": "Hello WhatsApp"}
                    }]
                }
            }]
        }]
    }
    await gw.handle_webhook(payload)
    assert len(dispatched) == 1
    assert dispatched[0].text == "Hello WhatsApp"

@pytest.mark.asyncio
async def test_whatsapp_send():
    gw = WhatsAppGateway("token", "phone", "verify")
    await gw.start()
    
    resp_mock = MagicMock()
    resp_mock.json.return_value = {"messages": [{"id": "wamid123"}]}
    mock_post = AsyncMock(return_value=resp_mock)
    gw._client.post = mock_post
    
    out = OutboundMessage(
        platform_id=PlatformID(Platform.WHATSAPP, "+1234567890"),
        text="Sending to WA",
        reply_to="wamid0"
    )
    await gw.send(out)
    
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert "messages" in args[0]
    payload = kwargs["json"]
    assert payload["to"] == "+1234567890"
    assert payload["text"]["body"] == "Sending to WA"
    assert payload["context"]["message_id"] == "wamid0"
    
    await gw.stop()

# === imessage.py tests ===

@pytest.fixture
def mock_imessage_platform():
    with patch("platform.system", return_value="Darwin"):
        yield

@pytest.mark.asyncio
async def test_imessage_lifecycle(tmp_path, mock_imessage_platform):
    db_path = tmp_path / "chat.db"
    # Create fake sqlite db
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE message (ROWID INTEGER PRIMARY KEY, text TEXT, is_from_me INTEGER, handle_id INTEGER, date INTEGER)")
    conn.execute("CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT)")
    conn.commit()
    conn.close()
    
    gw = iMessageGateway(db_path=db_path)
    await gw.start()
    assert gw._running
    assert gw._poll_task is not None
    await gw.stop()
    assert not gw._running

@pytest.mark.asyncio
async def test_imessage_send(mock_imessage_platform):
    gw = iMessageGateway(db_path=Path("fake"))
    
    with patch.object(iMessageGateway, "_run_applescript", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = True
        
        out = OutboundMessage(
            platform_id=PlatformID(Platform.IMESSAGE, "user@example.com"),
            text="Hello iMessage",
        )
        await gw.send(out)
        mock_run.assert_called_once()
        script = mock_run.call_args[0][0]
        assert "user@example.com" in script
        assert "Hello iMessage" in script

@pytest.mark.asyncio
async def test_imessage_fetch(tmp_path, mock_imessage_platform):
    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE message (ROWID INTEGER PRIMARY KEY, text TEXT, is_from_me INTEGER, handle_id INTEGER, date INTEGER)")
    conn.execute("CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT)")
    
    conn.execute("INSERT INTO handle (ROWID, id) VALUES (1, 'user1')")
    conn.execute("INSERT INTO message (ROWID, text, is_from_me, handle_id, date) VALUES (1, 'Hello', 0, 1, 1000)")
    # is_from_me = 1 should be ignored
    conn.execute("INSERT INTO message (ROWID, text, is_from_me, handle_id, date) VALUES (2, 'Hi', 1, 1, 1001)")
    conn.commit()
    conn.close()
    
    gw = iMessageGateway(db_path=db_path)
    gw._last_rowid = 0
    msgs = gw._fetch_new_messages()
    
    assert len(msgs) == 1
    assert msgs[0].text == "Hello"
    assert msgs[0].platform_id.sender_id == "user1"
