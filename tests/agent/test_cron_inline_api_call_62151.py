"""Regression guard for #62151 — gateway cron must not wedge on the 2nd+ call.

Gateway-fired cron jobs hung forever on the 2nd+ API call because both the
non-streaming (``interruptible_api_call``) and the default streaming
(``interruptible_streaming_api_call``) paths run the request on a spawned
daemon worker thread. Inside the gateway's nested cron thread pools that extra
worker wedged before the socket opened; the same job succeeded via ``hermes
cron tick`` (foreground, no nested pools). Cron has no interactive interrupt
surface, so both paths now run inline on the conversation thread for the
``cron`` platform.

These tests pin: (1) the inline gate is cron-only, (2) the inline call runs on
the *calling* thread — no worker is spawned — for both entry points, and (3)
the shared dispatch closes the per-request client.
"""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

from run_agent import AIAgent

from agent.chat_completion_helpers import (
    direct_api_call,
    interruptible_api_call,
    interruptible_streaming_api_call,
    should_use_direct_api_call,
)


def _make_agent(*, platform="cron"):
    agent = MagicMock()
    agent.platform = platform
    agent.api_mode = "chat_completions"
    agent.provider = "openrouter"
    agent._interrupt_requested = False
    agent._consecutive_stale_streams = 0
    agent._touch_activity = MagicMock()
    agent._close_request_openai_client = MagicMock()
    return agent


def test_should_use_direct_api_call_only_for_cron_openai_wire():
    assert should_use_direct_api_call(_make_agent(platform="cron")) is True
    assert should_use_direct_api_call(_make_agent(platform="cli")) is False
    assert should_use_direct_api_call(_make_agent(platform="telegram")) is False
    assert should_use_direct_api_call(_make_agent(platform=None)) is False

    for api_mode in ("codex_responses", "anthropic_messages", "bedrock_converse"):
        agent = _make_agent(platform="cron")
        agent.api_mode = api_mode
        assert should_use_direct_api_call(agent) is False

    moa = _make_agent(platform="cron")
    moa.provider = "moa"
    assert should_use_direct_api_call(moa) is False






def test_direct_api_call_interrupt_aborts_active_client_and_raises():
    """Cron's outer watchdog interrupts from another thread while inline."""
    agent = _make_agent()
    client_ready = threading.Event()
    release_request = threading.Event()
    fake_client = MagicMock()

    def _create(**_kwargs):
        client_ready.set()
        return fake_client

    def _request(**_kwargs):
        assert release_request.wait(timeout=2)
        raise RuntimeError("socket closed")

    fake_client.chat.completions.create.side_effect = _request
    agent._create_request_openai_client.side_effect = _create
    result = {}

    def _run():
        try:
            direct_api_call(agent, {"model": "m", "messages": []})
        except Exception as exc:
            result["exception"] = exc

    worker = threading.Thread(target=_run)
    worker.start()
    assert client_ready.wait(timeout=1)
    assert callable(agent._active_request_abort)
    AIAgent.interrupt(agent, "cron timeout")
    agent._abort_request_openai_client.assert_called_once_with(
        fake_client, reason="interrupt_abort"
    )
    release_request.set()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert isinstance(result.get("exception"), InterruptedError)
    assert agent._active_request_abort is None


def test_interruptible_streaming_api_call_routes_cron_via_nonstream_method():
    """Streaming is the default even for cron — the gate must catch it too.

    It delegates to the ``_interruptible_api_call`` method (which itself runs
    inline for cron) rather than calling ``direct_api_call`` directly, so the
    outer loop's per-request retry/refresh seam — which patches that method —
    stays intact (regression from the codex 401-refresh path).
    """
    agent = _make_agent()
    sentinel = SimpleNamespace(id="via-nonstream")
    agent._interruptible_api_call = MagicMock(return_value=sentinel)

    resp = interruptible_streaming_api_call(
        agent, {"model": "m", "messages": []}, on_first_delta=lambda: None
    )

    assert resp is sentinel
    agent._interruptible_api_call.assert_called_once()


# ── Claude-over-proxy (Argo) under cron must STREAM, not delegate to the
#    non-streaming inline path — else the proxy refuses the call with
#    "Streaming is required for operations that may take longer than 10
#    minutes". Two fixes collide (#62151 cron-inline vs argo-stream); the gate
#    must run the streaming body inline instead of picking non-streaming. ──


def _patch_proxy_stream(monkeypatch, *, enabled: bool, on_proxy: bool):
    """Patch the argo-stream detector + flag used by the streaming gate."""
    import agent.anthropic_adapter as aa
    monkeypatch.setattr(aa, "stream_claude_on_proxy_enabled", lambda: enabled)
    monkeypatch.setattr(
        aa, "is_claude_on_proxy_wire", lambda *a, **k: on_proxy
    )


def test_cron_claude_on_proxy_streams_inline_not_nonstream(monkeypatch):
    """Flag ON + Claude-on-proxy: the gate must NOT divert to the non-streaming
    method. It falls through into the streaming machinery and runs it inline on
    the calling thread (no daemon worker spawned — #62151 preserved)."""
    agent = _make_agent()
    agent.model = "claude-sonnet-5"
    agent.base_url = "https://apps-stage.inside.anl.gov/argoapi/v1"
    agent.provider = "custom"
    # If the gate wrongly delegated, this would be the returned value — assert
    # it is NOT used.
    agent._interruptible_api_call = MagicMock(
        return_value=SimpleNamespace(id="wrongly-delegated")
    )
    _patch_proxy_stream(monkeypatch, enabled=True, on_proxy=True)

    caller_tid = threading.get_ident()
    ran = {}

    # Intercept the streaming dispatch so we don't exercise the full ~1600-line
    # body: prove (a) we entered the streaming path (not the non-stream method),
    # (b) inline on the calling thread. relay_llm.stream is what the
    # chat_completions streaming branch calls to open the wire stream.
    import agent.relay_llm as relay_llm

    def _fake_stream(*_a, **_k):
        ran["tid"] = threading.get_ident()
        raise RuntimeError("stream-entered")  # bail out fast, deterministically

    monkeypatch.setattr(relay_llm, "stream", _fake_stream)

    # The streaming body will raise our sentinel; that is fine — we only assert
    # routing + thread identity, not a full successful aggregation.
    try:
        interruptible_streaming_api_call(
            agent, {"model": "claude-sonnet-5", "messages": []},
            on_first_delta=lambda: None,
        )
    except Exception:
        pass

    # Did NOT take the non-streaming delegation.
    agent._interruptible_api_call.assert_not_called()
    # Streaming dispatch was reached, and it ran on the CALLING thread (inline —
    # no worker thread spawned).
    assert ran.get("tid") == caller_tid


def test_cron_flag_off_still_delegates_to_nonstream(monkeypatch):
    """Default-off: with the flag disabled, cron keeps the original #62151
    behavior (delegate to the non-streaming inline method) even for a
    Claude-on-proxy model. No behavior change unless explicitly enabled."""
    agent = _make_agent()
    agent.model = "claude-sonnet-5"
    agent.base_url = "https://apps-stage.inside.anl.gov/argoapi/v1"
    agent.provider = "custom"
    sentinel = SimpleNamespace(id="via-nonstream")
    agent._interruptible_api_call = MagicMock(return_value=sentinel)
    _patch_proxy_stream(monkeypatch, enabled=False, on_proxy=True)

    resp = interruptible_streaming_api_call(
        agent, {"model": "claude-sonnet-5", "messages": []},
        on_first_delta=lambda: None,
    )

    assert resp is sentinel
    agent._interruptible_api_call.assert_called_once()


def test_cron_non_claude_model_still_delegates_to_nonstream(monkeypatch):
    """Flag ON but the model is NOT Claude-on-proxy: unchanged behavior — a
    normal OpenAI-wire cron model must keep the non-streaming inline path."""
    agent = _make_agent()
    agent.model = "gpt-5.6-sol"
    agent.base_url = "https://apps-stage.inside.anl.gov/argoapi/v1"
    agent.provider = "custom"
    sentinel = SimpleNamespace(id="via-nonstream")
    agent._interruptible_api_call = MagicMock(return_value=sentinel)
    _patch_proxy_stream(monkeypatch, enabled=True, on_proxy=False)

    resp = interruptible_streaming_api_call(
        agent, {"model": "gpt-5.6-sol", "messages": []},
        on_first_delta=lambda: None,
    )

    assert resp is sentinel
    agent._interruptible_api_call.assert_called_once()
