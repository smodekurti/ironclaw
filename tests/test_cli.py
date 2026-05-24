import pytest
import sys
from unittest.mock import patch
from ironclaw.cli.main import main

def run_cli(*args):
    with patch.object(sys, 'argv', ['ironclaw'] + list(args)):
        try:
            main()
            return 0
        except SystemExit as e:
            return e.code

def test_cli_help():
    assert run_cli("--help") == 0

def test_cli_setup():
    assert run_cli("setup", "--help") == 0

def test_cli_agent():
    assert run_cli("agent", "--help") == 0

def test_cli_config():
    assert run_cli("config", "--help") == 0

def test_cli_gateway():
    assert run_cli("gateway", "--help") == 0

def test_cli_orch():
    assert run_cli("orch", "--help") == 0

def test_cli_providers():
    assert run_cli("providers", "--help") == 0

def test_cli_skills():
    assert run_cli("skills", "--help") == 0

def test_cli_audit():
    assert run_cli("audit", "--help") == 0

def test_cli_session():
    assert run_cli("session", "--help") == 0

def test_cli_info():
    assert run_cli("info") == 0
