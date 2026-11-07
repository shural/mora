"""LLM annotation of lyrics via a local Ollama (works with cloud models too).

Fills in, per line: Chinese gloss, naturalness badge, grammar note.
And per content word: a short Chinese gloss.

Everything is best-effort: a failure leaves fields as null and the app still works.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Callable

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:31b-cloud")
TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "240"))

CONTENT_POS = {"名詞", "動詞", "形容詞", "形状詞", "副詞", "連体詞", "感動詞", "接頭辞", "接尾辞"}

SYSTEM = (
    "你是日语歌词教学助手，服务中文母语的日语学习者（N4~N3 水平）。"
    "你只输出 JSON，不要解释，不要 markdown 代码块。"
)

SCHEMA_HINT = (
    '对每一行输出：{"lines":[{"i":行号(整数),'
    '"gloss_zh":"整行的自然中文翻译，不要直译腔","text":"把这一行歌词原样抄一遍",'
    '"naturalness":"green|yellow|red",'
    '"note":"这句歌词的语法点/文语特征/当て字读法，中文，40字以内；没有就给空字符串",'
    '"words":[{"t":词下标,"gloss_zh":"该词在此语境下的中文意思，6字以内"}]}]}'
    "\n\nnaturalness 判定标准："
    "\n- green = 现代口语里可以直接这样说"
    "\n- yellow = 诗意/省略/倒装，但语法成立，看得懂也学得到"
    "\n- red = 只有歌词或文语才会出现（如「〜しか」「〜がたき」「如何にいます」「思ひ出づる」），日常说会显得很奇怪"
    "\n\nwords 只给实词（名词/动词/形容词/副词），虚词不给。t 必须是我给你的词下标。"
    "\n歌词里的「故郷」常读ふるさと、「運命」常读さだめ 这类当て字，如果 note 里能指出会很有用。"
)


class OllamaError(RuntimeError):
    pass


def _chat(messages: list[dict[str, str]], *, disable_thinking: bool = True) -> str:
    body: dict[str, Any] = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "num_predict": 2048},
    }
    if disable_thinking:
        body["think"] = False
    req = urllib.request.Request(
        OLLAMA_URL + "/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise OllamaError(f"连不上 Ollama ({OLLAMA_URL})：{e}") from e
    except json.JSONDecodeError as e:
        raise OllamaError(f"Ollama 返回的不是 JSON：{e}") from e
    msg = data.get("message") or {}
    return str(msg.get("content") or "")


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(text: str) -> Any:
    text = text.strip()
    m = _FENCE.search(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    raise OllamaError("模型没有返回可解析的 JSON")


def _content_words(tokens: list[dict[str, Any]]) -> list[tuple[int, str]]:
    out = []
    for i, t in enumerate(tokens):
        head = t["pos"].split("-")[0]
        if head in CONTENT_POS and t["surface"].strip():
            out.append((i, t["surface"]))
    return out


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _prompt_for(lines: list[dict[str, Any]], start_index: int) -> str:
    blocks = []
    for offset, line in enumerate(lines):
        words = _content_words(line["tokens"])
        wdesc = " ".join(f"{idx}{surface}" for idx, surface in words)
        blocks.append(f"{offset + 1}. {line['text']}    [词: {wdesc}]")
    return (
        "歌词行（编号. 句子  [词: 下标+词]），编号从 1 开始：\n"
        + "\n".join(blocks)
        + "\n\n"
        + SCHEMA_HINT
    )


def _apply(lines: list[dict[str, Any]], start_index: int, payload: Any) -> int:
    """Map the model's rows onto our lines.

    Models renumber, skip and reorder rows; so match by echoed text first,
    then by 1-based index, then by position. Never apply a row twice.
    """
    if not isinstance(payload, dict):
        return 0
    rows = payload.get("lines")
    if not isinstance(rows, list):
        return 0

    norm = lambda s: re.sub(r"[\s、。,.!?！？「」『』]", "", str(s or ""))
    used: set[int] = set()
    applied = 0

    for pos, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        target: int | None = None

        echoed = norm(row.get("text"))
        if echoed:
            for k, ln in enumerate(lines):
                if k in used:
                    continue
                if norm(ln["text"]).startswith(echoed[:12]) or echoed.startswith(norm(ln["text"])[:12]):
                    target = k
                    break

        if target is None:
            try:
                idx = int(row.get("i"))
            except (TypeError, ValueError):
                idx = 0
            if 1 <= idx <= len(lines) and (idx - 1) not in used:
                target = idx - 1

        if target is None and pos < len(lines) and pos not in used:
            target = pos

        if target is None or target in used:
            continue
        used.add(target)
        line = lines[target]

        gloss = row.get("gloss_zh")
        if isinstance(gloss, str) and gloss.strip():
            line["glossZh"] = gloss.strip()
        nat = row.get("naturalness")
        if nat in ("green", "yellow", "red"):
            line["naturalness"] = nat
            for t in line["tokens"]:
                t["naturalness"] = nat
        note = row.get("note")
        if isinstance(note, str) and note.strip():
            line["note"] = note.strip()
        for w in row.get("words") or []:
            if not isinstance(w, dict):
                continue
            try:
                ti = int(w.get("t"))
            except (TypeError, ValueError):
                continue
            if 0 <= ti < len(line["tokens"]):
                g = w.get("gloss_zh")
                if isinstance(g, str) and g.strip():
                    line["tokens"][ti]["glossZh"] = g.strip()
        applied += 1
    return applied


def annotate_song(song: dict[str, Any], progress: Callable[[float, str], None] | None = None) -> dict[str, Any]:
    """Annotate every line. Mutates `song` in place and returns it."""
    def tick(p: float, msg: str) -> None:
        if progress:
            progress(p, msg)

    lines = song.get("lines") or []
    if not lines:
        return song
    tick(2, "准备歌词…")
    groups = _chunks(lines, 6)
    done = 0
    for gi, group in enumerate(groups):
        start_index = gi * 6
        tick(5 + 88 * gi / max(1, len(groups)), f"AI 标注第 {start_index + 1}–{start_index + len(group)} 行…")
        prompt = _prompt_for(group, start_index)
        payload: Any = None
        for attempt in range(2):
            try:
                content = _chat([
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt if attempt == 0 else prompt + "\n\n只输出JSON对象，不要代码块。"},
                ])
                payload = extract_json(content)
                break
            except OllamaError:
                if attempt == 1:
                    raise
        done += _apply(lines, start_index, payload)
    # The model sometimes silently drops a row (duplicate lines confuse it).
    # Retry only the holes, one line per call.
    missing = [i for i, ln in enumerate(lines) if ln.get("naturalness") is None]
    for k, i in enumerate(missing[:6]):
        tick(90 + 8 * k / max(1, len(missing)), f"补标注第 {i + 1} 行…")
        try:
            content = _chat([
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": _prompt_for([lines[i]], 0)},
            ])
            done += _apply([lines[i]], 0, extract_json(content))
        except OllamaError:
            continue
    song["annotatedAt"] = True
    tick(100, f"已标注 {sum(1 for l in lines if l.get('glossZh'))}/{len(lines)} 行")
    return song


def annotate_one_token(song: dict[str, Any], line_id: str, token_id: str) -> dict[str, Any]:
    line = next((l for l in song["lines"] if l["id"] == line_id), None)
    if line is None:
        raise KeyError("line")
    tok = next((t for t in line["tokens"] if t["id"] == token_id), None)
    if tok is None:
        raise KeyError("token")
    prompt = (
        f"歌词整行：{line['text']}\n"
        f"要解释的词：{tok['surface']}（读音 {tok['kana']}，词性 {tok['pos']}）\n\n"
        '只输出 JSON：{"gloss_zh":"该词在此语境下的中文意思，6字以内",'
        '"note":"如果这个词有文语/当て字/易混淆之处，用中文说明20字以内；否则空字符串"}'
    )
    content = _chat([
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": prompt},
    ])
    data = extract_json(content)
    if isinstance(data, dict):
        g = data.get("gloss_zh")
        if isinstance(g, str) and g.strip():
            tok["glossZh"] = g.strip()
        n = data.get("note")
        if isinstance(n, str) and n.strip():
            merged = tok.get("note")
            tok["note"] = f"{merged}；{n.strip()}" if merged else n.strip()
    return tok


def health() -> dict[str, Any]:
    try:
        req = urllib.request.Request(OLLAMA_URL + "/api/tags")
        with urllib.request.urlopen(req, timeout=4) as r:
            tags = json.loads(r.read().decode("utf-8"))
        names = [m.get("name", "") for m in tags.get("models", [])]
        return {"ok": True, "model": OLLAMA_MODEL, "url": OLLAMA_URL,
                "installed": OLLAMA_MODEL in names}
    except Exception as e:  # noqa: BLE001 - health must never raise
        return {"ok": False, "model": OLLAMA_MODEL, "url": OLLAMA_URL, "reason": str(e)}
