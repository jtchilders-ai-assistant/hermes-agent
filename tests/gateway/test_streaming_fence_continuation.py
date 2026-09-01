"""Regression tests: streaming continuation must not resend or invert fences.

Bug: every streaming frame is passed through ``ensure_closed_code_fences``, so
a frame that stops mid-code-block carries a *synthetic* closing fence.
``_continuation_text`` compared the visible prefix against the final text with
an exact ``startswith``; the synthetic fence made that test fail and the
function fell through to returning the ENTIRE message.  The user saw the reply
twice, and because the two messages disagreed about fence state the client
rendered code as prose and prose as code.

These tests assert the *contract* (no duplicate resend, balanced fences per
message, lossless rejoin), not snapshots of the output text.
"""

import pytest

from gateway.stream_consumer import (
    ensure_closed_code_fences,
    strip_synthetic_code_fences,
)
from gateway.platforms.helpers import balance_fences_across_chunks

FENCE = "`" * 3


def _continuation(final_text: str, visible_prefix: str) -> str:
    """Mirror of ``GatewayStreamConsumer._continuation_text`` (no I/O)."""
    prefix = strip_synthetic_code_fences(visible_prefix, final_text)
    if prefix and final_text.startswith(prefix):
        tail = final_text[len(prefix):].lstrip()
        if not tail:
            return tail
        return balance_fences_across_chunks([prefix, tail])[1]
    return final_text


def _reply(lang: str = "python", nlines: int = 40) -> str:
    body = "\n".join(f"    x{i} = step({i})" for i in range(nlines))
    return (
        "Analysis of the scheduler run.\n\n"
        f"{FENCE}{lang}\n{body}\n{FENCE}\n\n"
        "Conclusion: backfill starves the wide jobs.\n"
    )


TWO_BLOCKS = (
    "Intro prose.\n\n"
    f"{FENCE}bash\ncmd --one\n{FENCE}\n\n"
    "Middle prose.\n\n"
    f"{FENCE}yaml\nkey: val\nk2: v2\n{FENCE}\n\n"
    "Final prose.\n"
)
INLINE = "Text with `inline` and an open `span that keeps going and going\n"
UNTAGGED = (
    "Intro.\n\n" + FENCE + "\n"
    + "\n".join(f"line{i}" for i in range(30))
    + "\n" + FENCE + "\nEnd prose.\n"
)

# (id, full_text, cut_marker) — cut lands at the marker's offset.
CASES = [
    ("cut_inside_fenced_block", _reply(), "x20"),
    ("cut_outside_fence", _reply(), "Conclusion"),
    ("cut_on_fence_open_line", _reply(), FENCE + "python"),
    ("cut_inside_inline_code", INLINE, "keeps"),
    ("cut_inside_untagged_fence", UNTAGGED, "line15"),
    ("cut_inside_second_block", TWO_BLOCKS, "k2"),
]
IDS = [c[0] for c in CASES]


@pytest.mark.parametrize("full,marker", [(c[1], c[2]) for c in CASES], ids=IDS)
def test_continuation_is_not_a_full_resend(full, marker):
    """The tail must be strictly shorter than the whole reply."""
    visible = ensure_closed_code_fences(full[: full.index(marker)])
    cont = _continuation(full, visible)
    assert cont.strip() != full.strip(), "entire message resent as a duplicate"
    assert len(cont) < len(full)


@pytest.mark.parametrize("full,marker", [(c[1], c[2]) for c in CASES], ids=IDS)
def test_each_delivered_message_is_fence_balanced(full, marker):
    """Neither message may leave a fence open — that is what inverts rendering."""
    visible = ensure_closed_code_fences(full[: full.index(marker)])
    cont = _continuation(full, visible)
    assert visible.count(FENCE) % 2 == 0
    assert cont.count(FENCE) % 2 == 0


def _content_lines(text: str) -> list[str]:
    """Non-blank lines that are not bare fence markers.

    Fence markers are presentation: the chunker legitimately closes and
    reopens them at a boundary. Everything else is content and must survive.
    """
    out = []
    for line in text.split("\n"):
        s = line.strip()
        if not s or s.startswith(FENCE):
            continue
        out.append(s)
    return out


@pytest.mark.parametrize("full,marker", [(c[1], c[2]) for c in CASES], ids=IDS)
def test_rejoin_is_lossless(full, marker):
    """prefix + continuation must preserve every content line, in order.

    Fence markers themselves are excluded: closing at the boundary and
    reopening on the tail is exactly what the fix is supposed to do.
    """
    cut = full.index(marker)
    visible = ensure_closed_code_fences(full[:cut])
    cont = _continuation(full, visible)

    real_prefix = strip_synthetic_code_fences(visible, full)
    assert full.startswith(real_prefix), "synthetic-strip corrupted the real prefix"

    assert _content_lines(real_prefix + cont) == _content_lines(full)


def test_strip_never_invents_a_prefix_the_final_text_lacks():
    """Whatever strip returns must still be a real prefix of the final text."""
    for _id, full, marker in CASES:
        visible = ensure_closed_code_fences(full[: full.index(marker)])
        stripped = strip_synthetic_code_fences(visible, full)
        assert full.startswith(stripped), _id


def test_strip_is_exact_inverse_of_ensure():
    """Round-trip: strip(ensure(x), reference=x) == x for open-marker text."""
    for partial in (
        "Intro\n\n" + FENCE + "python\nx = 1",
        "Intro\n\n" + FENCE + "\nplain",
        "Intro\n\n" + FENCE + "python\nx = 1\n\n",
        "prose with an open `inline span",
        "no markers at all",
    ):
        closed = ensure_closed_code_fences(partial)
        assert strip_synthetic_code_fences(closed, partial) == partial


def test_strip_preserves_genuine_trailing_fence():
    """A real closing fence from the model must NOT be stripped.

    ``reference`` is the arbiter: the complete text starts with itself, so the
    fast path returns it untouched.
    """
    complete = "Intro\n\n" + FENCE + "python\nx = 1\n" + FENCE
    assert ensure_closed_code_fences(complete) == complete
    assert strip_synthetic_code_fences(complete, complete) == complete
    # Without a reference the ambiguity is unresolvable, so nothing is stripped.
    assert strip_synthetic_code_fences(complete) == complete
    assert strip_synthetic_code_fences("Intro\n\n" + FENCE + "py\nx\n" + FENCE) == \
        "Intro\n\n" + FENCE + "py\nx\n" + FENCE


def test_strip_preserves_genuine_inline_backtick():
    complete = "Use `flag` to enable"
    assert strip_synthetic_code_fences(complete) == complete


def test_empty_and_non_string_inputs_are_safe():
    assert strip_synthetic_code_fences("") == ""
    assert strip_synthetic_code_fences(None) is None


def test_identical_prefix_yields_empty_continuation():
    """Nothing new to send when the visible text already is the final text."""
    full = _reply()
    assert _continuation(full, ensure_closed_code_fences(full)) == ""


def test_non_prefix_final_text_still_falls_back_to_full_send():
    """If the visible text genuinely is not a prefix, resending all is correct."""
    full = _reply()
    assert _continuation(full, "completely unrelated visible text") == full
