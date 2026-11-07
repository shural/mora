/**
 * Small, dependency-free Japanese helpers.
 *
 * The server is the source of truth for `kana`, `romaji` and `morae` on the
 * wire — these helpers exist for mock data and for recomputing a reading after
 * a manual "改读音" edit (PATCH /tokens).
 */

const SMALL_KANA = new Set([
  "ゃ",
  "ゅ",
  "ょ",
  "ぁ",
  "ぃ",
  "ぅ",
  "ぇ",
  "ぉ",
  "ゎ",
  "ゕ",
  "ゖ",
]);

const IGNORED = new Set([
  " ",
  "　",
  "・",
  "、",
  "。",
  "，",
  "．",
  "！",
  "？",
  "!",
  "?",
  ",",
  ".",
  "「",
  "」",
  "『",
  "』",
  "（",
  "）",
  "(",
  ")",
  "【",
  "】",
  "〜",
  "~",
  "-",
  "—",
  "–",
  "…",
  ":",
  ";",
  "：",
  "；",
  "“",
  "”",
  "'",
  "’",
]);

/** Katakana → hiragana (ー, ・ and punctuation are preserved). */
export function toHiragana(input: string): string {
  let out = "";
  for (const ch of input) {
    const code = ch.charCodeAt(0);
    if (code >= 0x30a1 && code <= 0x30f6) {
      out += String.fromCharCode(code - 0x60);
    } else {
      out += ch;
    }
  }
  return out;
}

function isKanaChar(ch: string): boolean {
  const code = ch.charCodeAt(0);
  return code >= 0x3041 && code <= 0x3096;
}

/**
 * Split a hiragana reading into morae.
 * - small kana attach to the previous mora (きょ = 1)
 * - っ / ー / ん are each their own mora
 * - punctuation, ・ and spaces yield no morae
 */
export function splitMorae(kana: string): string[] {
  const hira = toHiragana(kana);
  const morae: string[] = [];
  for (const ch of hira) {
    if (IGNORED.has(ch)) continue;
    if (!isKanaChar(ch) && ch !== "ー") continue;
    if (SMALL_KANA.has(ch) && morae.length > 0) {
      morae[morae.length - 1] += ch;
      continue;
    }
    morae.push(ch);
  }
  return morae;
}

const SINGLE_ROMAJI: Record<string, string> = {
  あ: "a",
  い: "i",
  う: "u",
  え: "e",
  お: "o",
  か: "ka",
  き: "ki",
  く: "ku",
  け: "ke",
  こ: "ko",
  が: "ga",
  ぎ: "gi",
  ぐ: "gu",
  げ: "ge",
  ご: "go",
  さ: "sa",
  し: "shi",
  す: "su",
  せ: "se",
  そ: "so",
  ざ: "za",
  じ: "ji",
  ず: "zu",
  ぜ: "ze",
  ぞ: "zo",
  た: "ta",
  ち: "chi",
  つ: "tsu",
  て: "te",
  と: "to",
  だ: "da",
  ぢ: "ji",
  づ: "zu",
  で: "de",
  ど: "do",
  な: "na",
  に: "ni",
  ぬ: "nu",
  ね: "ne",
  の: "no",
  は: "ha",
  ひ: "hi",
  ふ: "fu",
  へ: "he",
  ほ: "ho",
  ば: "ba",
  び: "bi",
  ぶ: "bu",
  べ: "be",
  ぼ: "bo",
  ぱ: "pa",
  ぴ: "pi",
  ぷ: "pu",
  ぺ: "pe",
  ぽ: "po",
  ま: "ma",
  み: "mi",
  む: "mu",
  め: "me",
  も: "mo",
  や: "ya",
  ゆ: "yu",
  よ: "yo",
  ら: "ra",
  り: "ri",
  る: "ru",
  れ: "re",
  ろ: "ro",
  わ: "wa",
  ゐ: "i",
  ゑ: "e",
  を: "o",
  ゔ: "vu",
  ん: "n",
};

const DIGRAPH_ROMAJI: Record<string, string> = {
  きゃ: "kya",
  きゅ: "kyu",
  きょ: "kyo",
  しゃ: "sha",
  しゅ: "shu",
  しょ: "sho",
  しぇ: "she",
  ちゃ: "cha",
  ちゅ: "chu",
  ちょ: "cho",
  ちぇ: "che",
  にゃ: "nya",
  にゅ: "nyu",
  にょ: "nyo",
  ひゃ: "hya",
  ひゅ: "hyu",
  ひょ: "hyo",
  みゃ: "mya",
  みゅ: "myu",
  みょ: "myo",
  りゃ: "rya",
  りゅ: "ryu",
  りょ: "ryo",
  ぎゃ: "gya",
  ぎゅ: "gyu",
  ぎょ: "gyo",
  じゃ: "ja",
  じゅ: "ju",
  じょ: "jo",
  じぇ: "je",
  びゃ: "bya",
  びゅ: "byu",
  びょ: "byo",
  ぴゃ: "pya",
  ぴゅ: "pyu",
  ぴょ: "pyo",
  てぃ: "ti",
  てゅ: "tyu",
  でぃ: "di",
  でゅ: "dyu",
  ふぁ: "fa",
  ふぃ: "fi",
  ふぇ: "fe",
  ふぉ: "fo",
  うぃ: "wi",
  うぇ: "we",
  うぉ: "wo",
  ゔぁ: "va",
  ゔぃ: "vi",
  ゔぇ: "ve",
  ゔぉ: "vo",
  ゔゅ: "vyu",
  つぁ: "tsa",
  つぃ: "tsi",
  つぇ: "tse",
  つぉ: "tso",
};

type Unit =
  | { kind: "syllable"; romaji: string }
  | { kind: "n" }
  | { kind: "sokuon" }
  | { kind: "long" };

function parseUnits(hira: string): Unit[] {
  const chars = Array.from(hira);
  const units: Unit[] = [];
  for (let i = 0; i < chars.length; i += 1) {
    const ch = chars[i];
    if (ch === undefined || IGNORED.has(ch)) continue;
    if (ch === "っ") {
      units.push({ kind: "sokuon" });
      continue;
    }
    if (ch === "ー") {
      units.push({ kind: "long" });
      continue;
    }
    if (ch === "ん") {
      units.push({ kind: "n" });
      continue;
    }
    const next = chars[i + 1];
    if (next !== undefined) {
      const pair = ch + next;
      const digraph = DIGRAPH_ROMAJI[pair];
      if (digraph !== undefined) {
        units.push({ kind: "syllable", romaji: digraph });
        i += 1;
        continue;
      }
    }
    const single = SINGLE_ROMAJI[ch];
    if (single !== undefined) {
      units.push({ kind: "syllable", romaji: single });
    }
  }
  return units;
}

function isVowel(ch: string): boolean {
  return ch === "a" || ch === "i" || ch === "u" || ch === "e" || ch === "o";
}

/**
 * Hepburn-ish romaji. し→shi, ち→chi, つ→tsu, ふ→fu, じ→ji, を→o, ん→n,
 * ー repeats the previous vowel, っ doubles the next consonant.
 */
export function toRomaji(kana: string): string {
  // A particle は / へ is read wa / e, and を is o.
  const units = parseUnits(toHiragana(kana));
  let out = "";
  let pendingSokuon = false;
  let lastVowel = "";
  for (const unit of units) {
    if (unit.kind === "sokuon") {
      pendingSokuon = true;
      continue;
    }
    if (unit.kind === "long") {
      out += lastVowel;
      continue;
    }
    if (unit.kind === "n") {
      out += "n";
      pendingSokuon = false;
      lastVowel = "";
      continue;
    }
    let romaji = unit.romaji;
    if (pendingSokuon) {
      const head = romaji.charAt(0);
      if (!isVowel(head) && head !== "") romaji = head + romaji;
      pendingSokuon = false;
    }
    out += romaji;
    lastVowel = romaji.charAt(romaji.length - 1);
    if (!isVowel(lastVowel)) lastVowel = "";
  }
  return out;
}

/** Particle-aware reading used when a token's pronunciation is overridden. */
export function romajiForToken(kana: string, pos: string): string {
  const hira = toHiragana(kana);
  if (pos.includes("助詞")) {
    if (hira === "は") return "wa";
    if (hira === "へ") return "e";
    if (hira === "を") return "o";
  }
  return toRomaji(kana);
}

/** Break a kana-only surface into mora-sized substrings when lengths line up. */
export function splitSurfaceByMorae(
  surface: string,
  kana: string,
  morae: string[],
): string[] | null {
  const surfaceHira = toHiragana(surface);
  const kanaHira = toHiragana(kana);
  if (surfaceHira !== kanaHira) return null;
  if (surface.length !== kanaHira.length) return null;
  const parts: string[] = [];
  let offset = 0;
  for (const mora of morae) {
    const len = Array.from(mora).length;
    parts.push(Array.from(surface).slice(offset, offset + len).join(""));
    offset += len;
  }
  if (offset !== Array.from(surface).length) return null;
  return parts;
}
