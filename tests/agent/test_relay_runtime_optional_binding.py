"""Regression coverage for an intentionally unavailable Relay binding."""

import logging

from agent import relay_runtime


def test_missing_optional_binding_uses_noop_without_gateway_warning(monkeypatch, caplog):
    def missing_binding(*, profile_key):
        raise ModuleNotFoundError("No module named 'nemo_relay'", name="nemo_relay")

    monkeypatch.setattr(relay_runtime, "RelayRuntime", missing_binding)
    registry = relay_runtime.RelayHostRegistry()

    with caplog.at_level(logging.DEBUG, logger="agent.relay_runtime"):
        host = registry.for_profile("intel-macos")

    assert isinstance(host, relay_runtime.NoopRelayRuntime)
    assert "runtime initialization failed" not in caplog.text
    assert "using the no-op Hermes Relay runtime" in caplog.text


def test_unexpected_runtime_failure_remains_a_warning(monkeypatch, caplog):
    def broken_runtime(*, profile_key):
        raise RuntimeError("broken relay")

    monkeypatch.setattr(relay_runtime, "RelayRuntime", broken_runtime)
    registry = relay_runtime.RelayHostRegistry()

    with caplog.at_level(logging.WARNING, logger="agent.relay_runtime"):
        host = registry.for_profile("broken")

    assert isinstance(host, relay_runtime.NoopRelayRuntime)
    assert "runtime initialization failed" in caplog.text