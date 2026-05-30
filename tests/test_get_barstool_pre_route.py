"""Pre-route tests for the get_barstool command."""

import importlib.util
import os

import pytest


def _load_command():
    here = os.path.dirname(os.path.abspath(__file__))
    cmd_path = os.path.join(here, "..", "commands", "get_barstool", "command.py")
    spec = importlib.util.spec_from_file_location("get_barstool_cmd_under_test", cmd_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.GetBarstoolCommand


@pytest.fixture
def cmd():
    return _load_command()()


class TestPreRouteBare:
    @pytest.mark.parametrize("phrase", [
        "what's on Barstool",
        "what's new on Barstool",
        "what's Barstool saying today",
        "give me Barstool headlines",
        "give me the latest Barstool",
        "latest from Barstool",
        "latest from Barstool Sports",
        "anything new on Barstool",
        "read me Barstool",
        "barstool",
        "barstool headlines",
        "barstool news",
    ])
    def test_bare(self, cmd, phrase):
        result = cmd.pre_route(phrase)
        assert result is not None
        assert result.arguments == {}


class TestPreRouteCategory:
    @pytest.mark.parametrize("phrase,category", [
        ("any Barstool NFL news", "nfl"),
        ("any Barstool nba news", "nba"),
        ("what's Barstool saying about the nfl", "nfl"),
        ("what's Barstool saying about nba", "nba"),
        ("barstool nfl", "nfl"),
        ("barstool mlb news", "mlb"),
        ("barstool golf", "golf"),
    ])
    def test_category(self, cmd, phrase, category):
        result = cmd.pre_route(phrase)
        assert result is not None
        assert result.arguments == {"category": category}


class TestPreRouteCount:
    @pytest.mark.parametrize("phrase,expected", [
        ("top 3 Barstool stories", {"count": 3}),
        ("top 10 Barstool headlines", {"count": 10}),
        ("give me one Barstool headline", {"count": 1}),
        ("give me five Barstool headlines", {"count": 5}),
    ])
    def test_top_n(self, cmd, phrase, expected):
        result = cmd.pre_route(phrase)
        assert result is not None
        assert result.arguments == expected


class TestPreRouteNoMatch:
    @pytest.mark.parametrize("phrase", [
        "tell me a joke",
        "what time is it",
        "news please",                # belongs to get_news, no "barstool" word
        "top 3 headlines",            # also belongs to get_news
        "",
    ])
    def test_returns_none(self, cmd, phrase):
        assert cmd.pre_route(phrase) is None


class TestFastPathPatterns:
    def test_ids_stable(self, cmd):
        ids = {p.id for p in cmd.fast_path_patterns}
        assert ids == {
            "get_barstool.top_n",
            "get_barstool.give_n",
            "get_barstool.category_any",
            "get_barstool.category_saying",
            "get_barstool.category_bare",
            "get_barstool.bare",
        }
