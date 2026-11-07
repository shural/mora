"""Compare what the learner sang against the lyric line.

Whisper transcribes the recording, we normalise both sides to morae, and diff.
Morae (not characters) because っ / ー / ん are exactly what learners drop,
and きょ is one beat but two characters.
"""
from __future__ import annotations

import difflib
from typing import Any

from . import jp


def morae_of_text(text: str) -> list[str]:
    out: list[str] = []
    for tok in jp.tokenize_line(text, "x"):
        out.extend(tok["morae"])
    return out


def target_morae(tokens: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for t in tokens:
        out.extend(t.get("morae") or [])
    return out


def _pairwise_replace(target: list[str], heard: list[str]) -> list[dict[str, Any]]:
    ops: list[dict[str, Any]] = []
    n = min(len(target), len(heard))
    for i in range(n):
        if target[i] == heard[i]:
            ops.append({"op": "eq", "a": target[i]})
        else:
            ops.append({"op": "sub", "a": target[i], "b": heard[i]})
    for t in target[n:]:
        ops.append({"op": "del", "a": t})
    for h in heard[n:]:
        ops.append({"op": "ins", "b": h})
    return ops


def diff_morae(target: list[str], heard: list[str]) -> dict[str, Any]:
    sm = difflib.SequenceMatcher(a=target, b=heard, autojunk=False)
    ops: list[dict[str, Any]] = []
    matched = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            matched += i2 - i1
            ops.extend({"op": "eq", "a": m} for m in target[i1:i2])
        elif tag == "delete":
            ops.extend({"op": "del", "a": m} for m in target[i1:i2])
        elif tag == "insert":
            ops.extend({"op": "ins", "b": m} for m in heard[j1:j2])
        else:
            ops.extend(_pairwise_replace(target[i1:i2], heard[j1:j2]))

    total = len(target)
    inserts = sum(1 for o in ops if o["op"] == "ins")
    score = 0 if total == 0 else round(max(0.0, matched / total * 100 - inserts * 2))
    return {
        "diff": ops,
        "score": int(score),
        "moraeOk": matched,
        "moraeTotal": total,
        "hint": _hint(ops),
    }


def _hint(ops: list[dict[str, Any]]) -> str:
    missing = [o["a"] for o in ops if o["op"] in ("del", "sub")]
    extra = [o["b"] for o in ops if o["op"] in ("ins", "sub") and o.get("b")]
    msgs: list[str] = []
    if "っ" in missing:
        msgs.append("丢掉了促音「っ」——要停一拍再发下一个音")
    if "ー" in missing:
        msgs.append("长音「ー」不够长——要把前一个元音再拖一拍")
    if "ん" in missing:
        msgs.append("拨音「ん」被吞掉了——它要单独占一拍")
    dropped = list(dict.fromkeys(m for m in missing if m not in ("っ", "ー", "ん")))[:4]
    if dropped and not msgs:
        msgs.append("漏掉了「" + "」「".join(dropped) + "」")
    extra_u = list(dict.fromkeys(extra))[:4]
    if extra_u and len(msgs) < 2:
        msgs.append("多唱了「" + "」「".join(extra_u) + "」")
    if not msgs:
        return "音节全对，继续跟唱找节奏"
    return "；".join(msgs)
