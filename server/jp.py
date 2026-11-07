"""Japanese text -> learning tokens.

Owns: kana/romaji conversion, mora splitting, furigana (ruby) alignment,
per-token flags (when a song word is read differently / is literary / is a
Chinese-speaker kanji trap).

Deliberately dependency-light: fugashi + unidic-lite only.
"""
from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------- kana basics

_KATA_TO_HIRA = {chr(c): chr(c - 0x60) for c in range(0x30A1, 0x30F7)}
_KATA_TO_HIRA["ヷ"] = "わ"
_KATA_TO_HIRA["ヸ"] = "ゐ"
_KATA_TO_HIRA["ヹ"] = "ゑ"
_KATA_TO_HIRA["ヺ"] = "を"
_KATA_TO_HIRA["ヵ"] = "ゕ"
_KATA_TO_HIRA["ヶ"] = "ゖ"

_SMALL = set("ゃゅょぁぃぅぇぉゎゕゖ")


def to_hiragana(text: str) -> str:
    return "".join(_KATA_TO_HIRA.get(ch, ch) for ch in text)


def _is_kana(ch: str) -> bool:
    return "\u3041" <= ch <= "\u3096" or ch == "ー" or "\u30a1" <= ch <= "\u30f6"


def _is_kanji(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x4E00 <= cp <= 0x9FFF
        or 0x3400 <= cp <= 0x4DBF
        or 0xF900 <= cp <= 0xFAFF
        or ch == "々"
        or ch == "〆"
    )


def split_morae(kana: str) -> list[str]:
    """Split a hiragana reading into morae.

    がっこう -> [が, っ, こ, う]   (4)
    きょう   -> [きょ, う]          (2)
    おんな   -> [お, ん, な]        (3)
    こーひー -> [こ, ー, ひ, ー]    (4)
    """
    kana = to_hiragana(kana)
    out: list[str] = []
    for ch in kana:
        if ch in " 　\t\n、。・「」『』（）()!?！？…~〜ー-–—":
            if ch == "ー" and out:
                out.append("ー")  # long vowel mark is its own mora
            continue
        if not _is_kana(ch):
            continue
        if ch in _SMALL and out and out[-1] != "ー":
            out[-1] += ch
        else:
            out.append(ch)
    return out


def mora_count(kana: str) -> int:
    return len(split_morae(kana))


_MORA_ROMAJI = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "ゐ": "i", "ゑ": "e", "を": "o",
    "ん": "n", "ゔ": "vu", "ゕ": "ka", "ゖ": "ke",
}
_MORA_ROMAJI.update({
    "きゃ": "kya", "きゅ": "kyu", "きょ": "kyo",
    "ぎゃ": "gya", "ぎゅ": "gyu", "ぎょ": "gyo",
    "しゃ": "sha", "しゅ": "shu", "しょ": "sho", "しぇ": "she",
    "じゃ": "ja", "じゅ": "ju", "じょ": "jo", "じぇ": "je",
    "ちゃ": "cha", "ちゅ": "chu", "ちょ": "cho", "ちぇ": "che",
    "ぢゃ": "ja", "ぢゅ": "ju", "ぢょ": "jo",
    "にゃ": "nya", "にゅ": "nyu", "にょ": "nyo",
    "ひゃ": "hya", "ひゅ": "hyu", "ひょ": "hyo",
    "びゃ": "bya", "びゅ": "byu", "びょ": "byo",
    "ぴゃ": "pya", "ぴゅ": "pyu", "ぴょ": "pyo",
    "みゃ": "mya", "みゅ": "myu", "みょ": "myo",
    "りゃ": "rya", "りゅ": "ryu", "りょ": "ryo",
    "ふぁ": "fa", "ふぃ": "fi", "ふぇ": "fe", "ふぉ": "fo", "ふゅ": "fyu",
    "てぃ": "ti", "てゅ": "tyu", "でぃ": "di", "でゅ": "dyu",
    "うぃ": "wi", "うぇ": "we", "うぉ": "wo",
    "ゔぁ": "va", "ゔぃ": "vi", "ゔぇ": "ve", "ゔぉ": "vo",
    "とぅ": "tu", "どぅ": "du",
    "いぇ": "ye", "くぁ": "kwa", "ぐぁ": "gwa",
})

_VOWELS = set("aiueo")
_PARTICLE_ROMAJI = {"は": "wa", "へ": "e", "を": "o"}


def to_romaji(kana: str, pos: str = "") -> str:
    """Hiragana -> Hepburn-ish romaji. Long vowels repeat, っ doubles."""
    morae = split_morae(kana)
    if not morae:
        return ""
    parts: list[str] = []
    prev_vowel = ""
    i = 0
    while i < len(morae):
        m = morae[i]
        if m == "ー":
            parts.append(prev_vowel or "")
            i += 1
            continue
        if m == "ん":
            nxt = morae[i + 1] if i + 1 < len(morae) else ""
            r = _MORA_ROMAJI.get(nxt, "")
            parts.append("n'" if r[:1] in _VOWELS or r[:1] == "y" else "n")
            prev_vowel = ""
            i += 1
            continue
        if m.startswith("っ") or m == "っ":
            nxt = _MORA_ROMAJI.get(morae[i + 1], "") if i + 1 < len(morae) else ""
            if nxt.startswith("ch"):
                parts.append("t")
            elif nxt:
                parts.append(nxt[0])
            i += 1
            continue
        r = _MORA_ROMAJI.get(m, m)
        parts.append(r)
        prev_vowel = r[-1] if r else ""
        i += 1
    out = "".join(parts)
    if pos in ("助詞", "助動詞") and len(morae) == 1:
        surface_kana = "".join(morae)
        if surface_kana in _PARTICLE_ROMAJI:
            out = _PARTICLE_ROMAJI[surface_kana]
    return out


# ---------------------------------------------------------------- furigana

def _runs(surface: str) -> list[tuple[bool, str]]:
    """Group surface into (is_kanji_run, text) chunks."""
    out: list[tuple[bool, str]] = []
    for ch in surface:
        k = _is_kanji(ch)
        if out and out[-1][0] == k:
            out[-1] = (k, out[-1][1] + ch)
        else:
            out.append((k, ch))
    return out


def align_ruby(surface: str, kana: str) -> list[dict[str, str]]:
    """Place the reading over the right part of the surface.

    兎/うさぎ          -> [{text:兎, rt:うさぎ}]
    追い/おい          -> [{text:追, rt:お}, {text:い}]
    忘れがたき/わすれがたき -> [{text:忘, rt:わす}, {text:れ}, {text:がた}, ...]
    Falls back to one ruby over the whole token when alignment is ambiguous.
    """
    if not surface:
        return []
    if not kana or not any(_is_kanji(c) for c in surface):
        return [{"text": surface}]

    reading = to_hiragana(kana)
    plain = "".join(ch if _is_kanji(ch) else to_hiragana(ch) for ch in surface)

    # Fast path: whole surface is kanji.
    if all(_is_kanji(c) for c in surface):
        return [{"text": surface, "rt": reading}]

    runs = _runs(surface)
    pieces: list[dict[str, str]] = []
    j = 0  # index into reading
    ok = True
    for idx, (is_kanji_run, text) in enumerate(runs):
        if not is_kanji_run:
            want = to_hiragana(text)
            if reading[j:j + len(want)] == want:
                pieces.append({"text": text})
                j += len(want)
            else:
                ok = False
                break
            continue
        # kanji run: how much reading until the next surface kana?
        nxt_kana = next((r[1] for r in runs[idx + 1:] if not r[0]), None)
        if nxt_kana is None:
            take = len(reading) - j
        else:
            want = to_hiragana(nxt_kana)
            found = -1
            for k in range(j + 1, len(reading) - len(want) + 1):
                if reading[k:k + len(want)] == want:
                    found = k
                    break
            take = (found - j) if found >= 0 else (len(reading) - j)
        if take <= 0:
            ok = False
            break
        pieces.append({"text": text, "rt": reading[j:j + take]})
        j += take
    if not ok or j != len(reading) or "".join(p["text"] for p in pieces) != surface:
        return [{"text": surface, "rt": reading}]
    return pieces


# ---------------------------------------------------------------- linguist notes

# Words whose in-song reading usually differs from the dictionary reading.
ATEJI_READINGS: dict[str, list[str]] = {
    "故郷": ["ふるさと", "こきょう"],
    "運命": ["さだめ", "うんめい"],
    "地球": ["ほし", "ちきゅう"],
    "永遠": ["とわ", "えいえん"],
    "理由": ["わけ", "りゆう"],
    "明日": ["あした", "あす", "みょうにち"],
    "如何": ["いかに", "どう", "いかが"],
    "父母": ["ちちはは", "ふぼ"],
    "思ひ": ["おもひ", "おもい"],
    "出づる": ["いづる", "でる"],
    "今日": ["きょう", "こんにち"],
    "奇跡": ["きせき"],
    "宇宙": ["そら", "うちゅう"],
    "青春": ["せいしゅん"],
    "喧嘩": ["けんか"],
    "大人": ["おとな"],
    "翼": ["つばさ"],
    "命": ["いのち"],
    "心": ["こころ"],
    "光": ["ひかり"],
    "夢": ["ゆめ"],
    "涙": ["なみだ"],
    "愛": ["あい"],
    "君": ["きみ"],
    "絆": ["きずな"],
}

# Classical-Japanese markers: do not copy these into conversation.
JODAI_TOKENS = {
    "しか", "がたき", "けり", "けむ", "らむ", "なり", "べし", "まし", "らし",
    "めり", "なり", "ぬ", "ず", "ざり", "き", "し", "しも", "て", "に", "を",
    "はも", "かな", "や", "よ", "ぞ", "なむ", "こそ", "いと", "うつつ",
}

# Same kanji, different meaning from Chinese. Ranked by how often they fool people.
KANJI_TRAPS: dict[str, str] = {
    "大丈夫": "没问题（不是「大丈夫」）",
    "勉強": "学习（不是「勉强」）",
    "手紙": "信（不是「手纸」）",
    "汽車": "火车（不是「汽车」）",
    "娘": "女儿（不是「娘」）",
    "愛人": "情人/小三（不是「爱人」）",
    "我慢": "忍耐（不是「我慢」）",
    "迷惑": "麻烦/困扰（不是「迷惑」）",
    "泥棒": "小偷（不是「泥棒」）",
    "新聞": "报纸（不是「新闻」）",
    "丈夫": "结实（不是「丈夫」）",
    "湯": "热水（不是「汤」）",
    "切手": "邮票（不是「切手」）",
    "薬": "药",
    "一生懸命": "拼命（不是「一生悬命」）",
    "無理": "勉强/不可能",
    "結構": "相当/不用了",
    "遠慮": "客气/谢绝（不是「远虑」）",
    "検討": "讨论研究（不是「检讨」）",
    "用意": "准备（不是「用意」）",
    "相当": "相当/颇",
    "出来る": "能做到",
}

_PUNCT_POS = {"記号", "補助記号", "空白", "句点", "読点", "括弧開", "括弧閉", "一般"}



# ---------------------------------------------------------------- word roles
# Particles and auxiliaries are the glue showing how a line's words relate, but
# they have no dictionary gloss. Give each a short Chinese role so a beginner can
# read the whole line as a sentence instead of a bag of nouns.

PARTICLE_ROLES: dict[str, str] = {
    "は": "主题（至于…）", "が": "主语", "を": "宾语", "に": "对象・时间・地点",
    "で": "地点・手段", "と": "和・引用", "へ": "朝向", "も": "也", "の": "的・所属",
    "から": "从・因为", "まで": "到", "より": "比", "や": "…等", "か": "疑问",
    "ね": "吧（求认同）", "よ": "呀（提醒）", "な": "啊／别", "わ": "语气", "ぞ": "强调",
    "ぜ": "强调", "って": "引用・话题", "など": "之类", "なんか": "之类的",
    "しか": "只（接否定）／文语过去", "だけ": "只有", "ばかり": "光是", "ほど": "程度",
    "くらい": "大约", "ぐらい": "大约", "ながら": "一边…一边", "ので": "因为",
    "のに": "却", "けど": "但是", "けれど": "但是", "ても": "即使", "でも": "即使／但是",
    "ば": "如果", "し": "并列", "て": "连接（て形）", "たり": "又…又…",
    "さ": "语气（强调）", "かな": "吧", "かも": "也许", "こそ": "正是", "とか": "之类",
    "とも": "也好…", "ばかりか": "岂止",
}

AUX_ROLES: dict[str, str] = {
    "な": "…的（连体形）", "だ": "断定（是）", "です": "是（礼貌）", "ます": "礼貌",
    "た": "过去", "ない": "否定", "ぬ": "否定", "ん": "否定／强调", "ず": "否定",
    "たい": "想", "れる": "被动／可能", "られる": "被动／可能", "せる": "使役",
    "させる": "使役", "う": "意志／推测", "よう": "意志／推测", "だろう": "大概",
    "でしょう": "大概", "らしい": "似乎", "みたい": "像", "そう": "好像",
    "き": "过去（文语）", "まい": "不会吧", "べき": "应该", "わけ": "道理／当然",
    "で": "中顿（…而）", "なき": "否定（文语）",
}

# 形状詞-助動詞語幹: 「ような」「そうな」 — manner, not a predicate
AUXSTEM_ROLES: dict[str, str] = {
    "よう": "像…一样", "そう": "好像", "みたい": "像", "らしい": "似乎",
    "べき": "应该", "わけ": "道理／当然", "はず": "应该", "つもり": "打算",
    "まま": "就那样", "ため": "为了／因为",
}

POS_ROLES: dict[str, str] = {
    "助詞": "助词", "助動詞": "助动词", "接続詞": "接续词",
    "接頭辞": "前缀", "接尾辞": "后缀", "感動詞": "感叹词",
}

# content words: these are what the line is *about*
CONTENT_POS = {"名詞", "代名詞", "動詞", "形容詞", "形状詞", "副詞", "連体詞", "接頭辞", "接尾辞"}


def pos_head(token: dict[str, Any]) -> str:
    return str(token.get("pos") or "").split("-")[0]


def role_of(token: dict[str, Any]) -> str | None:
    """Short Chinese grammatical role for a function word."""
    head = pos_head(token)
    surface = str(token.get("surface") or "")
    if "助動詞語幹" in str(token.get("pos") or ""):
        return AUXSTEM_ROLES.get(surface)
    if head == "助動詞":
        return AUX_ROLES.get(surface) or AUX_ROLES.get(str(token.get("dictForm") or "")) or POS_ROLES.get(head)
    if head == "助詞":
        return PARTICLE_ROLES.get(surface) or PARTICLE_ROLES.get(str(token.get("dictForm") or "")) or POS_ROLES.get(head)
    if head in CONTENT_POS:
        return None
    return POS_ROLES.get(head)


def apply_roles(tokens: list[dict[str, Any]]) -> None:
    """Fill `role` for function words (never touch a real gloss)."""
    for token in tokens:
        if token.get("glossZh"):
            continue
        role = role_of(token)
        if role:
            token["role"] = role


# ---------------------------------------------------------------- tokenizer

_tagger = None


def tagger():
    global _tagger
    if _tagger is None:
        import fugashi  # imported lazily: ~1s
        _tagger = fugashi.Tagger()
    return _tagger


def _feat(f, *names: str) -> str:
    for n in names:
        v = getattr(f, n, None)
        if v:
            return str(v)
    return ""


def tokenize_line(text: str, line_id: str) -> list[dict[str, Any]]:
    """Split one lyric line into contract `Token` objects."""
    toks: list[dict[str, Any]] = []
    for i, w in enumerate(tagger()(text)):
        surface = w.surface
        if not surface:
            continue
        f = w.feature
        pos1 = _feat(f, "pos1", "pos") or ""
        pos2 = _feat(f, "pos2", "pos2") or ""
        pos = pos1 + (("-" + pos2) if pos2 and pos2 != "*" else "")
        katakana = _feat(f, "kana", "katakana")
        pron = _feat(f, "pron", "pronunciation") or katakana
        lemma = _feat(f, "lemma", "base") or surface
        if lemma == "-" or lemma == "*":
            lemma = surface

        has_kanji = any(_is_kanji(c) for c in surface)
        is_punct = pos1 in _PUNCT_POS and not has_kanji and not _is_kana(surface[:1] or " ")

        if is_punct:
            toks.append({
                "id": f"{line_id}t{i}",
                "surface": surface,
                "ruby": [{"text": surface}],
                "kana": "",
                "romaji": "",
                "morae": [],
                "pos": pos1 or "記号",
                "dictForm": None,
                "glossZh": None,
                "naturalness": None,
                "note": None,
                "flags": [],
                "saved": False,
            })
            continue

        kana = to_hiragana(katakana) if katakana else to_hiragana(surface)
        if not has_kanji and not katakana:
            kana = to_hiragana(surface)
        morae = split_morae(kana)
        # Orthographic readings give the romaji learners actually type
        # (がっこう -> gakkou, not gakkoo). Particles need the spoken form.
        romaji_src = kana
        if pos1 in ("助詞", "助動詞") and pron:
            romaji_src = to_hiragana(pron)
        romaji = to_romaji(romaji_src, pos1)

        flags: list[str] = []
        note_parts: list[str] = []
        if surface in ATEJI_READINGS and kana not in ATEJI_READINGS[surface]:
            flags.append("ateji")
            alts = "・".join(ATEJI_READINGS[surface])
            note_parts.append(f"歌では「{alts}」と読むことがある（词典读法：{kana}）")
        elif has_kanji and any(r != kana for r in ATEJI_READINGS.get(surface, [])):
            flags.append("rare-reading")
            alts = "・".join(ATEJI_READINGS[surface])
            note_parts.append(f"词典读法：{kana}；歌里也可能读作「{alts}」（按实际演唱改）")
        if surface in JODAI_TOKENS and pos1 in ("助詞", "助動詞", "動詞", "形容詞"):
            flags.append("jodai")
        if surface in KANJI_TRAPS:
            flags.append("kanji-trap")
            note_parts.append(KANJI_TRAPS[surface])

        toks.append({
            "id": f"{line_id}t{i}",
            "surface": surface,
            "ruby": align_ruby(surface, kana),
            "kana": kana,
            "romaji": romaji,
            "morae": morae,
            "pos": pos,
            "dictForm": lemma if lemma != surface else None,
            "glossZh": None,
            "naturalness": None,
            "note": "；".join(note_parts) if note_parts else None,
            "flags": flags,
            "saved": False,
        })
    apply_roles(toks)
    return toks


def tokenize_lines(texts: list[str]) -> list[list[dict[str, Any]]]:
    return [tokenize_line(t, f"l{i}") for i, t in enumerate(texts)]


def split_lyrics(text: str) -> list[str]:
    lines = [ln.strip() for ln in text.replace("\r\n", "\n").split("\n")]
    return [ln for ln in lines if ln]


def line_gloss_hint(tokens: list[dict[str, Any]]) -> tuple[int, int]:
    """(kanji, morae) for a line - used for 字余り warnings."""
    return (
        sum(1 for t in tokens if any(_is_kanji(c) for c in t["surface"])),
        sum(len(t["morae"]) for t in tokens),
    )
