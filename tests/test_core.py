"""Unit tests for the dependency-light core.

Everything here is pure or needs only fugashi, so CI can run it in seconds:

    pip install "fastapi>=0.110" python-multipart pytest fugashi unidic-lite
    pytest tests -q

These cover the things that have actually broken or drifted in this project:
mora splitting (the unit the whole app is built on), romaji, furigana
alignment, particle roles, LRC credit filtering, the mora diff, and the
timeline sanitiser.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from server import jp, kana_diff, lyrics  # noqa: E402


# ---------------------------------------------------------------- morae

@pytest.mark.parametrize(
    ("kana", "expected"),
    [
        ("がっこう", ["が", "っ", "こ", "う"]),
        ("きょう", ["きょ", "う"]),
        ("おんな", ["お", "ん", "な"]),
        ("こーひー", ["こ", "ー", "ひ", "ー"]),
        ("しんぶん", ["し", "ん", "ぶ", "ん"]),
        ("うさぎおいしかのやま", list("うさぎおいしかのやま")),
    ],
)
def test_split_morae(kana, expected):
    assert jp.split_morae(kana) == expected


def test_morae_ignore_punctuation():
    assert jp.split_morae("あ、い。") == ["あ", "い"]


# ---------------------------------------------------------------- romaji

@pytest.mark.parametrize(
    ("kana", "expected"),
    [
        ("がっこう", "gakkou"),
        ("きょう", "kyou"),
        ("しんぶん", "shinbun"),
        ("ふるさと", "furusato"),
    ],
)
def test_to_romaji(kana, expected):
    assert jp.to_romaji(kana) == expected


# ---------------------------------------------------------------- furigana

def test_ruby_aligns_okurigana():
    tokens = {t["surface"]: t for t in jp.tokenize_line("兎追いしかの山", "l0")}
    # the reading must sit on the kanji, not the trailing kana
    assert tokens["追い"]["ruby"] == [
        {"text": "追", "rt": "お"},
        {"text": "い"},
    ]


def test_line_mora_count():
    tokens = jp.tokenize_line("兎追いしかの山", "l0")
    assert sum(len(t["morae"]) for t in tokens) == 10


# ---------------------------------------------------------------- roles

def test_particles_get_grammatical_roles():
    tokens = {t["surface"]: t for t in jp.tokenize_line("余計な物など無いよね", "l0")}
    # な here is the 助動詞 (attributive), not the sentence-final 終助詞
    assert tokens["な"]["role"] == "…的（连体形）"
    assert tokens["など"]["role"] == "之类"
    assert tokens["よ"]["role"] == "呀（提醒）"


def test_content_words_get_no_role():
    tokens = jp.tokenize_line("夢は今もめぐりて", "l0")
    assert all(t.get("role") is None for t in tokens if t["pos"].startswith("名詞"))


# ---------------------------------------------------------------- lrc

def test_parse_lrc_drops_credits_and_keeps_timings():
    raw = "\n".join(
        [
            "[ti:x]",
            "[00:01.54]词：飛鳥涼",
            "[00:02.43]Guitar：秋山浩徳",
            "[00:23.61]余計な物など無いよね",
            "[00:32.12]すべてが君と僕との愛の構えさ",
            "[00:42.13]",
        ]
    )
    rows = lyrics.parse_lrc(raw)
    assert [r["text"] for r in rows] == ["余計な物など無いよね", "すべてが君と僕との愛の構えさ"]
    assert rows[0]["start"] == pytest.approx(23.61)
    assert rows[0]["end"] == pytest.approx(32.12)


def test_parse_lrc_handles_colon_centiseconds():
    rows = lyrics.parse_lrc("[00:23:61]一行目")
    assert rows and rows[0]["start"] == pytest.approx(23.61)


# ---------------------------------------------------------------- diff

def test_kana_diff_reports_a_dropped_sokuon():
    result = kana_diff.diff_morae(list("がっこう"), list("がこう"))
    assert result["moraeTotal"] == 4
    assert result["moraeOk"] < 4
    assert "っ" in result["hint"]
    assert 0 <= result["score"] < 100


def test_kana_diff_perfect_scores_full():
    result = kana_diff.diff_morae(list("がっこう"), list("がっこう"))
    assert result["score"] == 100
    assert result["hint"]


# ---------------------------------------------------------------- timeline

def test_sanitize_timings_is_monotonic_and_bounded():
    from server.main import _sanitize_timings

    out = _sanitize_timings([(0.0, 5.0), (3.0, 9.0), (4.0, 60.0)])
    assert len(out) == 3
    for start, end in out:
        assert end > start
        assert end - start <= 15.01
    for i in range(len(out) - 1):
        assert out[i][1] <= out[i + 1][0] + 0.01


def test_timings_ok_rejects_a_mismatched_version():
    from server.main import _timings_ok

    # lyrics that plausibly cover most of a 220 s song
    lines = [
        {"start": 10.0, "end": 12.0},
        {"start": 12.0, "end": 210.0},
    ]
    assert _timings_ok(lines, duration=220.0)
    # the same timeline against a 160 s master is a different cut, not a shift
    assert not _timings_ok(lines, duration=220.0, ref_duration=160.0)
    # lyrics that stop a third of the way in are implausible
    assert not _timings_ok([{"start": 5.0, "end": 40.0}], duration=220.0)
    # nothing timed at all
    assert not _timings_ok([{"start": -1.0, "end": -1.0}], duration=220.0)
