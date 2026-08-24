"""Discord rejects any message over 2000 characters, so a long question card
has to be split -- without losing or reordering a single line."""
from discord_send import LIMIT, chunk


def test_short_text_is_one_chunk():
    assert chunk("hello") == ["hello"]


def test_empty_text_still_sends_something():
    # send_dm iterates over the result, so an empty list would send nothing.
    assert chunk("") == [""]


def test_every_chunk_is_within_the_limit():
    text = "\n".join(f"line {i} " + "x" * 60 for i in range(300))
    assert all(len(c) <= LIMIT for c in chunk(text))


def test_splitting_is_lossless():
    text = "\n".join(f"line {i} " + "x" * 60 for i in range(300))
    assert "\n".join(chunk(text)) == text


def test_split_happens_on_line_boundaries():
    text = "\n".join("y" * 100 for _ in range(60))
    assert all(not c.startswith("\n") and not c.endswith("\n") for c in chunk(text))


def test_a_single_over_long_line_is_hard_split():
    parts = chunk("z" * 4500)
    assert len(parts) == 3 and "".join(parts) == "z" * 4500


def test_long_line_after_normal_lines_keeps_both():
    text = "short\n" + "z" * 2500
    assert "".join(chunk(text)).replace("\n", "") == "short" + "z" * 2500
