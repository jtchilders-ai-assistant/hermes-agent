"""Tests for the model.disable_developer_role compat flag.

GPT-5/Codex models get their leading system message rewritten to
``role: "developer"``. Strict OpenAI-compatible gateways (ANL Argo) reject
that role outright, so the swap is gated behind a config flag that defaults
to OFF (upstream behavior preserved).
"""

import pytest

import agent.transports.chat_completions as cc
from agent.transports import get_transport


@pytest.fixture
def transport():
    return get_transport("chat_completions")


@pytest.fixture(autouse=True)
def _reset_flag_cache():
    """Each test owns the module-level cache."""
    cc._DISABLE_DEVELOPER_ROLE = None
    yield
    cc._DISABLE_DEVELOPER_ROLE = None


MSGS = [
    {"role": "system", "content": "You are a reviewer."},
    {"role": "user", "content": "hi"},
]


class TestDeveloperRoleSwapDefault:
    """Flag OFF => upstream behavior is unchanged."""

    def test_gpt5_still_swaps_to_developer(self, transport, monkeypatch):
        monkeypatch.setattr(cc, "_developer_role_disabled", lambda: False)
        kw = transport.build_kwargs(model="GPT-5.6 Sol", messages=list(MSGS))
        assert kw["messages"][0]["role"] == "developer"
        assert kw["messages"][0]["content"] == "You are a reviewer."

    def test_non_gpt5_model_never_swaps(self, transport, monkeypatch):
        monkeypatch.setattr(cc, "_developer_role_disabled", lambda: False)
        kw = transport.build_kwargs(model="claude-sonnet-5", messages=list(MSGS))
        assert kw["messages"][0]["role"] == "system"


class TestDeveloperRoleSwapDisabled:
    """Flag ON => the leading message stays role:system."""

    def test_gpt5_keeps_system_role(self, transport, monkeypatch):
        monkeypatch.setattr(cc, "_developer_role_disabled", lambda: True)
        kw = transport.build_kwargs(model="GPT-5.6 Sol", messages=list(MSGS))
        assert kw["messages"][0]["role"] == "system"

    def test_content_and_later_messages_untouched(self, transport, monkeypatch):
        monkeypatch.setattr(cc, "_developer_role_disabled", lambda: True)
        kw = transport.build_kwargs(model="gpt-5-codex", messages=list(MSGS))
        assert kw["messages"][0]["content"] == "You are a reviewer."
        assert kw["messages"][1] == {"role": "user", "content": "hi"}

    def test_caller_messages_not_mutated(self, transport, monkeypatch):
        """The transport must not rewrite the caller's stored history."""
        monkeypatch.setattr(cc, "_developer_role_disabled", lambda: True)
        original = list(MSGS)
        transport.build_kwargs(model="GPT-5.6 Sol", messages=original)
        assert original[0]["role"] == "system"


class TestDeveloperRoleFlagReader:
    """The config reader must cache and must fail safe."""

    def test_returns_false_when_config_raises(self, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("no config")

        monkeypatch.setattr("hermes_cli.config.load_config", _boom)
        cc._DISABLE_DEVELOPER_ROLE = None
        assert cc._developer_role_disabled() is False

    def test_reads_true_from_config(self, monkeypatch):
        monkeypatch.setattr("hermes_cli.config.load_config", lambda *a, **k: {})
        monkeypatch.setattr(
            "hermes_cli.config.cfg_get",
            lambda cfg, section, key, default=None: True,
        )
        cc._DISABLE_DEVELOPER_ROLE = None
        assert cc._developer_role_disabled() is True

    def test_result_is_cached(self, monkeypatch):
        calls = []

        def _counting_load(*a, **k):
            calls.append(1)
            return {}

        monkeypatch.setattr("hermes_cli.config.load_config", _counting_load)
        monkeypatch.setattr(
            "hermes_cli.config.cfg_get",
            lambda cfg, section, key, default=None: True,
        )
        cc._DISABLE_DEVELOPER_ROLE = None
        cc._developer_role_disabled()
        cc._developer_role_disabled()
        assert len(calls) == 1
