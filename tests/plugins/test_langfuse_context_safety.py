"""Regression coverage for Langfuse context ownership."""

import contextvars
from plugins.observability import langfuse as plugin


def test_root_trace_is_detached_but_preserves_propagated_attributes(monkeypatch):
    calls = []

    class Span:
        def start_observation(self, **kwargs):
            calls.append(("child", kwargs))
            return Span()

        def update_trace(self, **kwargs):
            pass

        def end(self):
            calls.append(("end", {}))

    class Attributes:
        def __enter__(self):
            calls.append(("attributes-enter", {}))

        def __exit__(self, *_args):
            calls.append(("attributes-exit", {}))

    class Client:
        def create_trace_id(self, seed=None):
            return "trace-id"

        def start_observation(self, **kwargs):
            calls.append(("detached", kwargs))
            return Span()

        def start_as_current_observation(self, **kwargs):
            calls.append(("current", kwargs))
            raise AssertionError("a long-lived root must not mutate the ambient OpenTelemetry context")

    monkeypatch.setattr(
        plugin,
        "propagate_attributes",
        lambda **kwargs: (calls.append(("attributes", kwargs)) or Attributes()),
    )
    state = contextvars.copy_context().run(
        plugin._start_root_trace,
        "task",
        task_id="task",
        session_id="session",
        platform="discord",
        provider="provider",
        model="model",
        api_mode="chat_completions",
        messages=[{"role": "user", "content": "hi"}],
        client=Client(),
    )
    sibling = contextvars.Context()
    child = sibling.run(
        plugin._start_child_observation,
        state,
        name="tool",
        as_type="tool",
        input_value={"argument": "value"},
    )
    sibling.run(plugin._end_observation, child)
    sibling.run(plugin._end_root, state, "root end()")

    assert state.root_ctx is None
    assert [name for name, _ in calls] == [
        "attributes", "attributes-enter", "detached", "attributes-exit", "child", "end", "end",
    ]
    assert calls[0][1] == {
        "session_id": "session", "trace_name": "Hermes turn", "tags": ["hermes", "langfuse"],
    }
    assert calls[2][1]["trace_context"] == {"trace_id": "trace-id", "session_id": "session"}
    assert calls[4][1]["name"] == "tool"
    assert all(name != "current" for name, _ in calls)
