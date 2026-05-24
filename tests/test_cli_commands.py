import argparse
import pytest
from unittest.mock import MagicMock, patch
import json
from pathlib import Path
import os
import sys

from ironclaw.cli.client import APIError, ServerUnavailableError

from ironclaw.cli.commands import (
    session,
    audit,
    config_cmd,
    agent,
)

@pytest.fixture
def mock_client():
    client = MagicMock()
    return client

@pytest.fixture
def mock_args():
    return argparse.Namespace(json=False)

# --- SESSION ---
def test_session_register():
    subparsers = MagicMock()
    session.register(subparsers)
    subparsers.add_parser.assert_called_with("session", help="Manage gateway sessions")

def test_session_dispatch_list_empty(mock_client, mock_args):
    mock_args.session_cmd = "list"
    mock_client.get_state.return_value = {}
    with patch("ironclaw.cli.commands.session.fmt.info") as mock_info:
        assert session.dispatch(mock_args, mock_client) == 0
        mock_info.assert_called_with("No active sessions found in shared state.")

def test_session_dispatch_list_with_data(mock_client, mock_args):
    mock_args.session_cmd = "list"
    mock_client.get_state.return_value = {
        "session:test:123": {"agent_id": "bot", "message_count": 5},
        "other_key": "ignore"
    }
    with patch("ironclaw.cli.commands.session.fmt.table") as mock_table:
        assert session.dispatch(mock_args, mock_client) == 0
        mock_table.assert_called_once()

def test_session_dispatch_list_json(mock_client, mock_args):
    mock_args.session_cmd = "list"
    mock_args.json = True
    mock_client.get_state.return_value = {"session:test": {}}
    with patch("ironclaw.cli.commands.session.fmt.json_out") as mock_json:
        assert session.dispatch(mock_args, mock_client) == 0
        mock_json.assert_called_once()

def test_session_dispatch_clear(mock_client, mock_args):
    mock_args.session_cmd = "clear"
    mock_args.key = "session:test"
    with patch("ironclaw.cli.commands.session.fmt.success") as mock_succ:
        assert session.dispatch(mock_args, mock_client) == 0
        mock_client.delete_state.assert_called_with("session:test")
        mock_succ.assert_called_once()

def test_session_dispatch_clear_json(mock_client, mock_args):
    mock_args.session_cmd = "clear"
    mock_args.key = "session:test"
    mock_args.json = True
    mock_client.delete_state.return_value = {"deleted": True}
    with patch("ironclaw.cli.commands.session.fmt.json_out") as mock_json:
        assert session.dispatch(mock_args, mock_client) == 0
        mock_json.assert_called_with({"deleted": True})

def test_session_dispatch_clear_all(mock_client, mock_args):
    mock_args.session_cmd = "clear-all"
    mock_client.get_state.return_value = {"session:1": {}, "session:2": {}, "other": 1}
    with patch("ironclaw.cli.commands.session.fmt.success") as mock_succ:
        assert session.dispatch(mock_args, mock_client) == 0
        assert mock_client.delete_state.call_count == 2
        mock_succ.assert_called_once()

def test_session_dispatch_clear_all_empty(mock_client, mock_args):
    mock_args.session_cmd = "clear-all"
    mock_client.get_state.return_value = {"other": 1}
    with patch("ironclaw.cli.commands.session.fmt.info") as mock_info:
        assert session.dispatch(mock_args, mock_client) == 0
        mock_info.assert_called_once()

def test_session_dispatch_clear_all_json(mock_client, mock_args):
    mock_args.session_cmd = "clear-all"
    mock_args.json = True
    mock_client.get_state.return_value = {"session:1": {}}
    with patch("ironclaw.cli.commands.session.fmt.json_out") as mock_json:
        assert session.dispatch(mock_args, mock_client) == 0
        mock_json.assert_called_with({"deleted": ["session:1"]})

def test_session_dispatch_errors(mock_client, mock_args):
    mock_args.session_cmd = "list"
    mock_client.get_state.side_effect = ServerUnavailableError("down")
    with patch("ironclaw.cli.commands.session.fmt.error") as mock_err:
        assert session.dispatch(mock_args, mock_client) == 1
        mock_err.assert_called_with("down")

    mock_client.get_state.side_effect = APIError(status=500, detail="api err")
    with patch("ironclaw.cli.commands.session.fmt.error") as mock_err:
        assert session.dispatch(mock_args, mock_client) == 1
        mock_err.assert_called_with("HTTP 500: api err")

def test_session_dispatch_unknown(mock_client, mock_args):
    mock_args.session_cmd = "unknown"
    with patch("ironclaw.cli.commands.session.fmt.error") as mock_err:
        assert session.dispatch(mock_args, mock_client) == 1
        mock_err.assert_called_once()

# --- AUDIT ---
def test_audit_register():
    subparsers = MagicMock()
    audit.register(subparsers)
    subparsers.add_parser.assert_called_with("audit", help="Inspect the audit log")

def test_audit_dispatch_tail(mock_client, mock_args):
    mock_args.audit_cmd = "tail"
    mock_args.n = 10
    mock_client.audit_tail.return_value = [{"event": "agent_run_start", "agent_id": "test"}]
    with patch("ironclaw.cli.commands.audit._print_entries") as mock_print:
        assert audit.dispatch(mock_args, mock_client) == 0
        mock_print.assert_called_once()

def test_audit_dispatch_tail_json(mock_client, mock_args):
    mock_args.audit_cmd = "tail"
    mock_args.n = 10
    mock_args.json = True
    mock_client.audit_tail.return_value = [{"event": "test"}]
    with patch("ironclaw.cli.commands.audit.fmt.json_out") as mock_json:
        assert audit.dispatch(mock_args, mock_client) == 0
        mock_json.assert_called_once()

def test_audit_dispatch_search(mock_client, mock_args):
    mock_args.audit_cmd = "search"
    mock_args.event = "event_x"
    mock_args.agent_id = "agent_y"
    mock_args.n = 5
    mock_client.audit_search.return_value = []
    with patch("ironclaw.cli.commands.audit._print_entries"):
        assert audit.dispatch(mock_args, mock_client) == 0
        mock_client.audit_search.assert_called_with(event="event_x", agent_id="agent_y", n=5)

def test_audit_dispatch_search_json(mock_client, mock_args):
    mock_args.audit_cmd = "search"
    mock_args.event = "event_x"
    mock_args.agent_id = "agent_y"
    mock_args.n = 5
    mock_args.json = True
    mock_client.audit_search.return_value = [{"event": "test"}]
    with patch("ironclaw.cli.commands.audit.fmt.json_out") as mock_json:
        assert audit.dispatch(mock_args, mock_client) == 0
        mock_json.assert_called_once()

def test_audit_dispatch_verify(mock_client, mock_args):
    mock_args.audit_cmd = "verify"
    mock_client.audit_tail.return_value = [{"hmac": "123"}, {"hmac": "456"}, {"nohmac": "789"}]
    with patch("ironclaw.cli.commands.audit.fmt.success") as mock_succ, patch("ironclaw.cli.commands.audit.fmt.warn") as mock_warn:
        assert audit.dispatch(mock_args, mock_client) == 0
        mock_succ.assert_called_once()
        mock_warn.assert_called_once()

def test_audit_dispatch_verify_no_hmac(mock_client, mock_args):
    mock_args.audit_cmd = "verify"
    mock_client.audit_tail.return_value = [{"event": "1"}]
    with patch("ironclaw.cli.commands.audit.fmt.warn") as mock_warn:
        assert audit.dispatch(mock_args, mock_client) == 0
        mock_warn.assert_called_once()

def test_audit_dispatch_verify_json(mock_client, mock_args):
    mock_args.audit_cmd = "verify"
    mock_args.json = True
    mock_client.audit_tail.return_value = [{"hmac": "123"}, {"event": "2"}]
    with patch("ironclaw.cli.commands.audit.fmt.json_out") as mock_json:
        assert audit.dispatch(mock_args, mock_client) == 0
        mock_json.assert_called_with({"entries_checked": 2, "hmac_present": False})

def test_audit_dispatch_export(mock_client, mock_args, tmp_path):
    mock_args.audit_cmd = "export"
    mock_args.n = 2
    f_path = tmp_path / "out.jsonl"
    mock_args.out = str(f_path)
    mock_client.audit_tail.return_value = [{"event": "1"}, {"event": "2"}]
    with patch("ironclaw.cli.commands.audit.fmt.success"):
        assert audit.dispatch(mock_args, mock_client) == 0
    content = f_path.read_text()
    assert len(content.splitlines()) == 2

def test_audit_dispatch_export_stdout(mock_client, mock_args, capsys):
    mock_args.audit_cmd = "export"
    mock_args.n = 1
    mock_args.out = "-"
    mock_client.audit_tail.return_value = [{"event": "stdout_test"}]
    assert audit.dispatch(mock_args, mock_client) == 0
    captured = capsys.readouterr()
    assert "stdout_test" in captured.out

def test_audit_errors(mock_client, mock_args):
    mock_args.audit_cmd = "tail"
    mock_args.n = 10
    mock_client.audit_tail.side_effect = ServerUnavailableError("down")
    with patch("ironclaw.cli.commands.audit.fmt.error"):
        assert audit.dispatch(mock_args, mock_client) == 1

def test_audit_unknown(mock_client, mock_args):
    mock_args.audit_cmd = "unknown"
    with patch("ironclaw.cli.commands.audit.fmt.error"):
        assert audit.dispatch(mock_args, mock_client) == 1

def test_audit_print_entries(capsys):
    entries = [{"event": "agent_run_start", "agent_id": "bot", "timestamp": "2025-01-01"}]
    audit._print_entries(entries)
    captured = capsys.readouterr()
    assert "agent_run_start" in captured.out
    
    with patch("ironclaw.cli.commands.audit.fmt.info") as mock_info:
        audit._print_entries([])
        mock_info.assert_called_with("No audit entries found.")

# --- CONFIG ---
def test_config_register():
    subparsers = MagicMock()
    config_cmd.register(subparsers)
    subparsers.add_parser.assert_called_with("config", help="Show or edit IronClaw configuration")

@patch("ironclaw.cli.commands.config_cmd._find_config")
def test_config_show(mock_find, mock_args):
    mock_args.config_cmd = "show"
    mock_find.return_value = None
    with patch("ironclaw.cli.commands.config_cmd.fmt.section") as mock_sec:
        assert config_cmd.dispatch(mock_args, None) == 0
        mock_sec.assert_called()

@patch("ironclaw.cli.commands.config_cmd._find_config")
def test_config_show_json(mock_find, mock_args):
    mock_args.config_cmd = "show"
    mock_args.json = True
    mock_find.return_value = None
    with patch("ironclaw.cli.commands.config_cmd.fmt.json_out") as mock_json:
        assert config_cmd.dispatch(mock_args, None) == 0
        mock_json.assert_called_once()

def test_config_init(mock_args, tmp_path):
    mock_args.config_cmd = "init"
    f_path = tmp_path / "ironclaw.toml"
    mock_args.path = str(f_path)
    
    with patch("ironclaw.cli.commands.config_cmd.fmt.success"):
        assert config_cmd.dispatch(mock_args, None) == 0
    assert f_path.exists()
    
    # Try again
    with patch("ironclaw.cli.commands.config_cmd.fmt.warn") as mock_warn:
        assert config_cmd.dispatch(mock_args, None) == 1
        mock_warn.assert_called_once()

@patch("ironclaw.cli.commands.config_cmd._find_config")
def test_config_set(mock_find, mock_args, tmp_path):
    mock_args.config_cmd = "set"
    mock_args.key = "server.port"
    mock_args.value = "8080"
    f_path = tmp_path / "ironclaw.toml"
    mock_find.return_value = f_path
    
    with patch("ironclaw.cli.commands.config_cmd.fmt.success"):
        assert config_cmd.dispatch(mock_args, None) == 0
    assert f_path.exists()
    content = f_path.read_text()
    assert 'port = "8080"' in content or 'port = 8080' in content

def test_config_unknown(mock_args):
    mock_args.config_cmd = "unknown"
    with patch("ironclaw.cli.commands.config_cmd.fmt.error"):
        assert config_cmd.dispatch(mock_args, None) == 1

# --- AGENT ---
def test_agent_register():
    subparsers = MagicMock()
    agent.register(subparsers)
    subparsers.add_parser.assert_called_with("agent", help="Manage agents")

def test_agent_list(mock_client, mock_args):
    mock_args.agent_cmd = "list"
    mock_client.list_agents.return_value = [{"agent_id": "bot1"}, {"agent_id": "bot2"}]
    with patch("ironclaw.cli.commands.agent.fmt.table") as mock_table:
        assert agent.dispatch(mock_args, mock_client) == 0
        mock_table.assert_called_once()

def test_agent_list_empty(mock_client, mock_args):
    mock_args.agent_cmd = "list"
    mock_client.list_agents.return_value = []
    with patch("ironclaw.cli.commands.agent.fmt.info") as mock_info:
        assert agent.dispatch(mock_args, mock_client) == 0
        mock_info.assert_called_once()

def test_agent_list_json(mock_client, mock_args):
    mock_args.agent_cmd = "list"
    mock_args.json = True
    mock_client.list_agents.return_value = []
    with patch("ironclaw.cli.commands.agent.fmt.json_out") as mock_json:
        assert agent.dispatch(mock_args, mock_client) == 0
        mock_json.assert_called_once()

def test_agent_create_legacy(mock_client, mock_args):
    mock_args.agent_cmd = "create"
    mock_args.agent_id = "testbot"
    mock_args.name = "Test Bot"
    mock_args.system_prompt = "Hello"
    mock_args.provider = "anthropic"
    mock_args.model = "claude"
    mock_args.caps = []
    mock_args.tools = []
    mock_args.roots = []
    mock_args.cmds = []
    mock_args.api_key = ""
    mock_args.dry_run = False
    mock_client.create_agent.return_value = {"agent_id": "testbot"}
    
    with patch("ironclaw.cli.commands.agent.fmt.success") as mock_succ, patch("ironclaw.cli.commands.agent.fmt.key_value"):
        assert agent.dispatch(mock_args, mock_client) == 0
        mock_succ.assert_called_once()
        mock_client.create_agent.assert_called_once()

def test_agent_create_file(mock_client, mock_args, tmp_path):
    mock_args.agent_cmd = "create"
    mock_args.file = str(tmp_path / "spec.json")
    mock_args.set = ["agentId=mybot"]
    mock_args.dry_run = False
    
    with open(mock_args.file, "w") as f:
        json.dump({"agentId": "oldbot"}, f)
        
    mock_client.post.return_value = {"agentId": "mybot", "warnings": ["warn1"]}
    with patch("ironclaw.cli.commands.agent.fmt.success") as mock_succ, patch("ironclaw.cli.commands.agent.fmt.warn") as mock_warn:
        assert agent.dispatch(mock_args, mock_client) == 0
        mock_succ.assert_called_once()
        mock_warn.assert_called_once()

def test_agent_create_dry_run(mock_client, mock_args, tmp_path):
    mock_args.agent_cmd = "create"
    mock_args.file = str(tmp_path / "spec.json")
    mock_args.set = []
    mock_args.dry_run = True
    
    with open(mock_args.file, "w") as f:
        json.dump({"agentId": "test"}, f)
        
    mock_client.post.return_value = {"plan": {"agentId": "test"}}
    with patch("ironclaw.cli.commands.agent.fmt.section") as mock_sec, patch("ironclaw.cli.commands.agent.fmt.key_value"):
        assert agent.dispatch(mock_args, mock_client) == 0
        mock_sec.assert_called_with("Dry-run plan")

def test_agent_create_chat(mock_client, mock_args):
    mock_args.agent_cmd = "create-chat"
    mock_args.session_id = "sess"
    
    with patch("builtins.input", side_effect=["hello", "exit"]):
        mock_client.chat_sync_ace.return_value = "hi"
        assert agent.dispatch(mock_args, mock_client) == 0
        mock_client.chat_sync_ace.assert_called_once()

def test_agent_export(mock_client, mock_args, capsys):
    mock_args.agent_cmd = "export"
    mock_args.agent_id = "testbot"
    mock_args.output = None
    mock_client.get.return_value = {"spec": {"id": "testbot"}}
    
    assert agent.dispatch(mock_args, mock_client) == 0
    out = capsys.readouterr().out
    assert "testbot" in out

def test_agent_delete(mock_client, mock_args):
    mock_args.agent_cmd = "delete"
    mock_args.agent_id = "bot1"
    with patch("ironclaw.cli.commands.agent.fmt.success"):
        assert agent.dispatch(mock_args, mock_client) == 0
        mock_client.delete_agent.assert_called_with("bot1")

def test_agent_show(mock_client, mock_args):
    mock_args.agent_cmd = "show"
    mock_args.agent_id = "bot1"
    mock_args.limit = 10
    mock_client.list_agents.return_value = [{"agent_id": "bot1", "name": "B1"}]
    mock_client.get_history.return_value = [{"role": "assistant", "content": "hi", "timestamp": "now"}]
    
    with patch("ironclaw.cli.commands.agent.fmt.section") as mock_sec, patch("ironclaw.cli.commands.agent.fmt.key_value"):
        assert agent.dispatch(mock_args, mock_client) == 0
        assert mock_sec.call_count == 2

def test_agent_chat(mock_client, mock_args):
    mock_args.agent_cmd = "chat"
    mock_args.agent_id = "bot1"
    mock_args.session_id = "123"
    
    with patch("builtins.input", side_effect=["ping", "quit"]):
        mock_client.chat_sync.return_value = "pong"
        assert agent.dispatch(mock_args, mock_client) == 0
        mock_client.chat_sync.assert_called_once()

def test_agent_run(mock_client, mock_args, capsys):
    mock_args.agent_cmd = "run"
    mock_args.agent_id = "bot1"
    mock_args.message = "hello"
    mock_args.session_id = ""
    mock_client.chat_sync.return_value = "reply"
    
    assert agent.dispatch(mock_args, mock_client) == 0
    assert "reply" in capsys.readouterr().out

def test_agent_history(mock_client, mock_args, capsys):
    mock_args.agent_cmd = "history"
    mock_args.agent_id = "bot1"
    mock_args.limit = 50
    mock_client.get_history.return_value = [{"role": "user", "content": "test msg", "timestamp": "now"}]
    
    assert agent.dispatch(mock_args, mock_client) == 0
    assert "test msg" in capsys.readouterr().out

def test_agent_clear(mock_client, mock_args):
    mock_args.agent_cmd = "clear"
    mock_args.agent_id = "bot1"
    with patch("ironclaw.cli.commands.agent.fmt.success"):
        assert agent.dispatch(mock_args, mock_client) == 0
        mock_client.clear_history.assert_called_with("bot1")

def test_agent_errors(mock_client, mock_args):
    mock_args.agent_cmd = "list"
    mock_client.list_agents.side_effect = ServerUnavailableError("err")
    with patch("ironclaw.cli.commands.agent.fmt.error"):
        assert agent.dispatch(mock_args, mock_client) == 1
        
    mock_client.list_agents.side_effect = APIError(status=500, detail="err2")
    with patch("ironclaw.cli.commands.agent.fmt.error"):
        assert agent.dispatch(mock_args, mock_client) == 1

def test_agent_unknown(mock_client, mock_args):
    mock_args.agent_cmd = "unknown"
    with patch("ironclaw.cli.commands.agent.fmt.error"):
        assert agent.dispatch(mock_args, mock_client) == 1
