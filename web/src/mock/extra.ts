import type { Line, Naturalness, Song, Token, TokenFlag } from "../types";
import { romajiForToken, splitMorae, toHiragana } from "../lib/japanese";

/**
 * Two additional mock songs so the library, the unsynced state and the
 * "nothing saved yet" review state are all demoable without a backend.
 * ふるさと itself comes verbatim from contract/fixtures/song.json.
 */

interface TokenSpec {
  s: string;
  k?: string;
  pos: string;
  gloss?: string | null;
  nat?: Naturalness | null;
  note?: string | null;
  flags?: TokenFlag[];
  dict?: string | null;
}

interface LineSpec {
  text: string;
  tokens: TokenSpec[];
  start?: number;
  end?: number;
  gloss?: string | null;
  nat?: Naturalness | null;
  note?: string | null;
}

interface SongSpec {
  id: string;
  title: string;
  artist: string;
  duration: number;
  hue: number;
  synced: boolean;
  createdAt: string;
  lines: LineSpec[];
}

function makeRuby(surface: string, kana: string): Token["ruby"] {
  if (kana === "" || toHiragana(surface) === kana) {
    return [{ text: surface }];
  }
  return [{ text: surface, rt: kana }];
}

function makeToken(id: string, spec: TokenSpec, fallbackNat: Naturalness | null): Token {
  const kana = spec.k ?? toHiragana(spec.s);
  return {
    id,
    surface: spec.s,
    ruby: makeRuby(spec.s, kana),
    kana,
    romaji: romajiForToken(kana, spec.pos),
    morae: splitMorae(kana),
    pos: spec.pos,
    dictForm: spec.dict ?? null,
    glossZh: spec.gloss ?? null,
    naturalness: spec.nat === undefined ? fallbackNat : spec.nat,
    note: spec.note ?? null,
    flags: spec.flags ?? [],
    saved: false,
  };
}

function makeSong(spec: SongSpec): Song {
  const lines: Line[] = spec.lines.map((lineSpec, lineIndex) => {
    const lineId = `${spec.id}-l${lineIndex}`;
    return {
      id: lineId,
      text: lineSpec.text,
      start: spec.synced ? (lineSpec.start ?? -1) : -1,
      end: spec.synced ? (lineSpec.end ?? -1) : -1,
      glossZh: lineSpec.gloss ?? null,
      naturalness: lineSpec.nat ?? null,
      note: lineSpec.note ?? null,
      tokens: lineSpec.tokens.map((tokenSpec, tokenIndex) =>
        makeToken(`${lineId}t${tokenIndex}`, tokenSpec, lineSpec.nat ?? null),
      ),
    };
  });

  return {
    id: spec.id,
    title: spec.title,
    artist: spec.artist,
    duration: spec.duration,
    audioUrl: `/api/media/${spec.id}/audio`,
    coverUrl: null,
    sourceUrl: null,
    offset: 0,
    synced: spec.synced,
    createdAt: spec.createdAt,
    cards: [],
    lines,
  };
}

const sakura = makeSong({
  id: "sakura",
  title: "さくらさくら",
  artist: "日本古謡",
  duration: 74,
  hue: 28,
  synced: true,
  createdAt: "2026-11-06T21:10:00+08:00",
  lines: [
    {
      text: "さくらさくら",
      start: 4,
      end: 12.5,
      gloss: "樱花啊，樱花啊",
      nat: "green",
      tokens: [
        { s: "さくら", pos: "名詞-普通名詞", gloss: "樱花" },
        { s: "さくら", pos: "名詞-普通名詞", gloss: "樱花" },
      ],
    },
    {
      text: "やよいの空は",
      start: 13.5,
      end: 22,
      gloss: "弥生时节的天空",
      nat: "yellow",
      note: "「弥生」是旧历三月的雅称，樱花正开。",
      tokens: [
        { s: "やよい", pos: "名詞-普通名詞", gloss: "弥生（旧历三月）", dict: "弥生" },
        { s: "の", pos: "助詞-格助詞", gloss: "的" },
        { s: "空", k: "そら", pos: "名詞-普通名詞", gloss: "天空" },
        { s: "は", pos: "助詞-係助詞", gloss: "（主题助词）" },
      ],
    },
    {
      text: "見わたす限り",
      start: 23,
      end: 31.5,
      gloss: "放眼望去，一望无际",
      nat: "yellow",
      tokens: [
        { s: "見わたす", k: "みわたす", pos: "動詞-一般", gloss: "放眼望去", dict: "見渡す" },
        { s: "限り", k: "かぎり", pos: "名詞-普通名詞", gloss: "尽头、范围", dict: "限り" },
      ],
    },
    {
      text: "かすみか雲か",
      start: 32.5,
      end: 41,
      gloss: "是霞，还是云",
      nat: "yellow",
      tokens: [
        { s: "かすみ", k: "かすみ", pos: "名詞-普通名詞", gloss: "霞、薄雾", dict: "霞" },
        { s: "か", pos: "助詞-副助詞", gloss: "是……还是……" },
        { s: "雲", k: "くも", pos: "名詞-普通名詞", gloss: "云" },
        { s: "か", pos: "助詞-副助詞", gloss: "是……还是……" },
      ],
    },
    {
      text: "匂いぞ出ずる",
      start: 42,
      end: 50.5,
      gloss: "香气阵阵飘出",
      nat: "red",
      note: "整句是文语：「ぞ」强调，「出ずる」是古语。口语：香りがあふれ出る。",
      tokens: [
        { s: "匂い", k: "におい", pos: "名詞-普通名詞", gloss: "香气" },
        { s: "ぞ", pos: "助詞-係助詞", gloss: "（文语强调助词）", flags: ["jodai"] },
        {
          s: "出ずる",
          k: "いずる",
          pos: "動詞-一般",
          gloss: "出来、出现",
          dict: "出ず",
          flags: ["jodai"],
        },
      ],
    },
    {
      text: "いざやいざや",
      start: 51.5,
      end: 60,
      gloss: "来吧，来吧",
      nat: "red",
      note: "「いざや」是文语劝诱，现代说「さあ、行こう」。",
      tokens: [
        { s: "いざや", k: "いざや", pos: "感動詞-一般", gloss: "来吧", flags: ["jodai"] },
        { s: "いざや", k: "いざや", pos: "感動詞-一般", gloss: "来吧", flags: ["jodai"] },
      ],
    },
    {
      text: "見にゆかん",
      start: 61,
      end: 69,
      gloss: "去赏花吧",
      nat: "yellow",
      note: "「ゆかん」＝「行かむ」，古语的意志形；现代说「見に行こう」。",
      tokens: [
        { s: "見", k: "み", pos: "動詞-非自立可能", gloss: "看", dict: "見る" },
        { s: "に", pos: "助詞-格助詞", gloss: "去（做某事）" },
        {
          s: "ゆかん",
          k: "ゆかん",
          pos: "助動詞",
          gloss: "（文语意志形）……吧",
          flags: ["jodai"],
          dict: "行く",
        },
      ],
    },
  ],
});

const tsukinofune = makeSong({
  id: "tsukinofune",
  title: "月の舟",
  artist: "Mora 示例",
  duration: 62,
  hue: 196,
  synced: false,
  createdAt: "2026-11-07T18:40:00+08:00",
  lines: [
    {
      text: "夜の海に舟を浮かべ",
      tokens: [
        { s: "夜", k: "よる", pos: "名詞-普通名詞" },
        { s: "の", pos: "助詞-格助詞" },
        { s: "海", k: "うみ", pos: "名詞-普通名詞" },
        { s: "に", pos: "助詞-格助詞" },
        { s: "舟", k: "ふね", pos: "名詞-普通名詞" },
        { s: "を", pos: "助詞-格助詞" },
        { s: "浮かべ", k: "うかべ", pos: "動詞-一般", dict: "浮かべる" },
      ],
    },
    {
      text: "月のひかりを漕いでゆく",
      tokens: [
        { s: "月", k: "つき", pos: "名詞-普通名詞" },
        { s: "の", pos: "助詞-格助詞" },
        { s: "ひかり", k: "ひかり", pos: "名詞-普通名詞" },
        { s: "を", pos: "助詞-格助詞" },
        { s: "漕いで", k: "こいで", pos: "動詞-一般", dict: "漕ぐ" },
        { s: "ゆく", k: "ゆく", pos: "動詞-非自立可能", dict: "行く" },
      ],
    },
    {
      text: "遠い街の灯がにじむ",
      tokens: [
        { s: "遠い", k: "とおい", pos: "形容詞-一般" },
        { s: "街", k: "まち", pos: "名詞-普通名詞" },
        { s: "の", pos: "助詞-格助詞" },
        { s: "灯", k: "ひ", pos: "名詞-普通名詞" },
        { s: "が", pos: "助詞-格助詞" },
        { s: "にじむ", k: "にじむ", pos: "動詞-一般" },
      ],
    },
    {
      text: "名前のない歌をうたう",
      tokens: [
        { s: "名前", k: "なまえ", pos: "名詞-普通名詞" },
        { s: "の", pos: "助詞-格助詞" },
        { s: "ない", k: "ない", pos: "形容詞-一般" },
        { s: "歌", k: "うた", pos: "名詞-普通名詞" },
        { s: "を", pos: "助詞-格助詞" },
        { s: "うたう", k: "うたう", pos: "動詞-一般" },
      ],
    },
  ],
});

export interface ExtraCardSpec {
  songId: string;
  lineId: string;
  tokenId: string;
}

export const EXTRA_SONGS: Song[] = [sakura, tsukinofune];

export const EXTRA_CARDS: ExtraCardSpec[] = [
  { songId: "sakura", lineId: "sakura-l1", tokenId: "sakura-l1t0" },
];

export const EXTRA_HUES: Record<string, number> = {
  sakura: 28,
  tsukinofune: 196,
};
