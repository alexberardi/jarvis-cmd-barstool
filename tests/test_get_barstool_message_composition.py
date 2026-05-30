"""Verify GetBarstoolCommand.run() returns a spoken `message` on the pre-route fast path."""

import importlib.util
import os

import pytest


def _load_command():
    here = os.path.dirname(os.path.abspath(__file__))
    cmd_path = os.path.join(here, "..", "commands", "get_barstool", "command.py")
    spec = importlib.util.spec_from_file_location("barstool_msg_test", cmd_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cmd_module():
    return _load_command()


def _stub_entries(n: int, sport: str = "nfl"):
    return [
        {
            "title": f"Story {i + 1}",
            "url": f"https://barstool.example.com/blog/{i}",
            "published": "2026-05-30",
            "kind": "blog",
            "categories": [sport],
        }
        for i in range(n)
    ]


def test_message_composed_when_pre_routed(cmd_module, monkeypatch):
    cmd = cmd_module.GetBarstoolCommand()
    monkeypatch.setattr(cmd, "_fetch_latest_entries", lambda: _stub_entries(3))

    from core.request_information import RequestInformation
    req = RequestInformation(
        voice_command="barstool",
        conversation_id="c",
        is_validation_response=False,
        is_pre_routed=True,
    )
    resp = cmd.run(req)
    assert resp.context_data.get("message")
    assert "Story 1" in resp.context_data["message"]


def test_no_message_when_not_pre_routed(cmd_module, monkeypatch):
    cmd = cmd_module.GetBarstoolCommand()
    monkeypatch.setattr(cmd, "_fetch_latest_entries", lambda: _stub_entries(2))

    from core.request_information import RequestInformation
    req = RequestInformation(
        voice_command="barstool",
        conversation_id="c",
        is_validation_response=False,
        is_pre_routed=False,
    )
    resp = cmd.run(req)
    assert resp.context_data.get("message") is None


def test_compose_no_articles(cmd_module):
    msg = cmd_module._compose_barstool_message([], "all")
    assert "couldn't find" in msg.lower() or "no" in msg.lower()


def test_compose_category_no_match(cmd_module):
    msg = cmd_module._compose_barstool_message([], "nfl")
    assert "nfl" in msg.lower()
