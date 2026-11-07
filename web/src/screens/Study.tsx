import { useMemo, useRef, useState, type FormEvent } from "react";
import { annotate, createCard, deleteCard, getSong, patchToken } from "../api";
import type { Line, Song, Token } from "../types";
import { FLAG_LABEL } from "../types";
import { useJobPoller } from "../hooks/useJobPoller";
import { useLocalStorage } from "../hooks/useLocalStorage";
import { useRuntimeMode } from "../hooks/useRuntimeMode";
import { useToast } from "../components/Toast";
import { JobProgress } from "../components/JobProgress";
import { NaturalnessBadge, NaturalnessDot } from "../components/Naturalness";
import { RubyText } from "../components/RubyText";
import { IconBookmark, IconCheck, IconSparkle } from "../components/Icons";
import { cn } from "../lib/cn";
import { toMessage } from "../lib/errors";

interface Selected {
  line: Line;
  lineIndex: number;
  token: Token;
}

function firstMeaningfulToken(song: Song): Selected | null {
  for (let lineIndex = 0; lineIndex < song.lines.length; lineIndex += 1) {
    const line = song.lines[lineIndex];
    if (line === undefined) continue;
    const token = line.tokens.find((item) => item.morae.length > 0) ?? line.tokens[0];
    if (token !== undefined) return { line, lineIndex, token };
  }
  return null;
}


const CONTENT_HEADS = new Set([
  "名詞", "代名詞", "動詞", "形容詞", "形状詞", "副詞", "連体詞", "接頭辞", "接尾辞",
]);

const POS_LABEL: Record<string, string> = {
  名詞: "名词", 代名詞: "代词", 動詞: "动词", 形容詞: "形容词", 形状詞: "形容动词",
  副詞: "副词", 連体詞: "连体词", 接続詞: "接续词", 感動詞: "感叹词",
  助詞: "助词", 助動詞: "助动词", 接頭辞: "前缀", 接尾辞: "后缀", 記号: "标点",
};

function posHead(token: Token): string {
  return token.pos.split("-")[0] ?? token.pos;
}

function isContentWord(token: Token): boolean {
  return CONTENT_HEADS.has(posHead(token));
}

/** Bunsetsu-ish grouping: particles/auxiliaries stick to the word before them,
 *  so すべてが / 君と / 僕と / の / 愛の / 構えさ reads as phrases, not tokens. */
function groupTokens(tokens: Token[]): Token[][] {
  const groups: Token[][] = [];
  for (const token of tokens) {
    if (token.morae.length === 0) continue; // punctuation stays out of the strip
    if (groups.length === 0 || isContentWord(token)) groups.push([token]);
    else groups[groups.length - 1]?.push(token);
  }
  return groups;
}

interface Props {
  song: Song;
  onSongChange: (song: Song) => void;
}

/** 読む — lyrics + per-token study panel. */
export function Study({ song, onSongChange }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(() => {
    const first = firstMeaningfulToken(song);
    return first?.token.id ?? null;
  });
  const [busy, setBusy] = useState(false);
  const [reading, setReading] = useState<string | null>(null);
  const [readingError, setReadingError] = useState<string | null>(null);
  const annotateJob = useJobPoller();
  const [showWords, setShowWords] = useLocalStorage("mora.study.wordStrip", true);
  const panelRef = useRef<HTMLElement | null>(null);
  const lyricsRef = useRef<HTMLElement | null>(null);
  const { toast } = useToast();
  const mode = useRuntimeMode();

  const tokenIndex = useMemo(() => {
    const map = new Map<string, Selected>();
    for (let lineIndex = 0; lineIndex < song.lines.length; lineIndex += 1) {
      const line = song.lines[lineIndex];
      if (line === undefined) continue;
      for (const token of line.tokens) map.set(token.id, { line, lineIndex, token });
    }
    return map;
  }, [song.lines]);

  const selected: Selected | null =
    (selectedId !== null ? tokenIndex.get(selectedId) ?? null : null) ??
    firstMeaningfulToken(song);

  const selectToken = (tokenId: string) => {
    setSelectedId(tokenId);
    setReading(null);
    setReadingError(null);
    // On a narrow screen the panel sits under the lyrics; bring it into view.
    if (window.matchMedia("(max-width: 1000px)").matches) {
      window.requestAnimationFrame(() => {
        panelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
  };

  const backToLyrics = () => {
    lyricsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const refresh = async () => {
    const updated = await getSong(song.id);
    onSongChange(updated);
    return updated;
  };

  const runAnnotate = async () => {
    const result = await annotateJob.run(() => annotate(song.id));
    if (result === null) return;
    try {
      await refresh();
      toast(
        mode === "mock" ? "演示模式：示例歌词已包含部分注解" : "注解完成",
        "success",
      );
    } catch (unknownError) {
      toast(toMessage(unknownError), "error");
    }
  };

  const toggleCard = async () => {
    if (selected === null || busy) return;
    setBusy(true);
    try {
      const existing = song.cards.find((card) => card.tokenId === selected.token.id);
      if (existing !== undefined) {
        await deleteCard(existing.id);
        toast("已从复习卡移出");
      } else {
        await createCard({
          songId: song.id,
          lineId: selected.line.id,
          tokenId: selected.token.id,
        });
        toast("已加入「覚える」", "success");
      }
      await refresh();
    } catch (unknownError) {
      toast(toMessage(unknownError), "error");
    } finally {
      setBusy(false);
    }
  };

  const startReading = () => {
    if (selected === null) return;
    setReading(selected.token.kana);
    setReadingError(null);
  };

  const submitReading = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (selected === null) return;
    const kana = (reading ?? "").trim();
    if (kana === "") {
      setReadingError("读音不能为空。");
      return;
    }
    setBusy(true);
    setReadingError(null);
    try {
      const updated = await patchToken(song.id, selected.token.id, { kana });
      onSongChange(updated);
      setReading(null);
      toast("读音已更新", "success");
    } catch (unknownError) {
      setReadingError(toMessage(unknownError));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="study">
      <div className="study-bar">
        <div className="nat-legend" aria-label="自然度说明">
          <span className="eyebrow">自然度</span>
          <span className="legend-item">
            <span aria-hidden="true">🟢</span> 日常可用
          </span>
          <span className="legend-dot" aria-hidden="true" />
          <span className="legend-item">
            <span aria-hidden="true">🟡</span> 诗意但成立
          </span>
          <span className="legend-dot" aria-hidden="true" />
          <span className="legend-item">
            <span aria-hidden="true">🔴</span> 只存在于歌词
          </span>
        </div>
        <div className="study-tools">
          <button
            type="button"
            className={cn("btn btn--ghost btn--small", showWords && "is-on")}
            onClick={() => setShowWords((value) => !value)}
            aria-pressed={showWords}
            title="在每句歌词下面摊开每个词的中文意思"
          >
            逐词释义
          </button>
          <JobProgress job={annotateJob.job} error={annotateJob.error} running={annotateJob.running} />
          <button
            type="button"
            className="btn btn--ghost btn--small"
            onClick={() => void runAnnotate()}
            disabled={annotateJob.running}
          >
            <IconSparkle size={15} />
            {annotateJob.running ? "正在注释…" : "AI 注释"}
          </button>
        </div>
      </div>

      <div className="study-grid">
        <section className="study-lyrics" aria-label="歌词与注释" ref={lyricsRef}>
          <p className="study-tip">
            {showWords
              ? "每句下面摊开了所有词：实词是意思，助词标出它连接的关系。点任意一个词看读音和语气。"
              : "点任意一个词，查看它的读音、词性和语气。"}
          </p>
          {song.lines.map((line, lineIndex) => (
            <article
              className={cn(
                "study-line",
                selected !== null && selected.line.id === line.id && "is-current-line",
              )}
              key={line.id}
            >
              <div className="study-rail">
                <span title={line.naturalness ?? "未标注自然度"}>
                  <NaturalnessDot value={line.naturalness} />
                </span>
                <span className="study-index">{String(lineIndex + 1).padStart(2, "0")}</span>
              </div>
              <div className="study-body">
                <p className="study-text" lang="ja">
                  {line.tokens.map((token) => (
                    <button
                      key={token.id}
                      type="button"
                      className={cn(
                        "study-token",
                        selected !== null && selected.token.id === token.id && "is-selected",
                        token.saved && "is-saved",
                      )}
                      onClick={() => selectToken(token.id)}
                      aria-pressed={selected !== null && selected.token.id === token.id}
                    >
                      <RubyText segments={token.ruby} showFurigana />
                    </button>
                  ))}
                </p>
                {showWords && (
                  <div className="word-strip">
                    {groupTokens(line.tokens).map((group, groupIndex) => (
                      <span className="word-group" key={`${line.id}-g${groupIndex}`}>
                        {group.map((token) => (
                          <button
                            key={token.id}
                            type="button"
                            className={cn(
                              "word-chip",
                              isContentWord(token) ? "word-chip--content" : "word-chip--glue",
                              selected !== null && selected.token.id === token.id && "is-selected",
                              token.saved && "is-saved",
                            )}
                            onClick={() => selectToken(token.id)}
                            title={`${token.kana || token.surface}${token.romaji ? ` · ${token.romaji}` : ""}`}
                          >
                            <span className="word-chip-jp" lang="ja">
                              {token.surface}
                            </span>
                            <span className="word-chip-zh">
                              {token.glossZh ?? token.role ?? POS_LABEL[posHead(token)] ?? ""}
                            </span>
                          </button>
                        ))}
                      </span>
                    ))}
                  </div>
                )}
                {line.glossZh !== null && <p className="study-gloss">{line.glossZh}</p>}
              </div>
            </article>
          ))}
        </section>

        <aside className="token-panel" aria-label="词条详情" ref={panelRef}>
          {selected === null ? (
            <div className="panel-empty">
              <p className="panel-empty-title">点一个词</p>
              <p className="panel-empty-text">读音、词性、释义和自然度会出现在这里。</p>
            </div>
          ) : (
            <div className="panel-inner" key={selected.token.id}>
              <div className="panel-kicker">
                第 {selected.lineIndex + 1} 行
                <span className="meta-dot" aria-hidden="true" />
                {selected.token.pos.split("-")[0] ?? selected.token.pos}
                {selected.token.saved && (
                  <span className="panel-saved-flag">
                    <IconCheck size={12} /> 已存卡
                  </span>
                )}
                <button type="button" className="panel-back" onClick={backToLyrics}>
                  ↑ 歌词
                </button>
              </div>

              <div className="panel-surface" lang="ja">
                <RubyText segments={selected.token.ruby} showFurigana />
              </div>
              <div className="panel-reading">
                <span className="panel-kana" lang="ja">
                  {selected.token.kana !== "" ? selected.token.kana : "—"}
                </span>
                {selected.token.romaji !== "" && (
                  <span className="panel-romaji">{selected.token.romaji}</span>
                )}
              </div>

              <dl className="panel-facts">
                <div>
                  <dt>词性</dt>
                  <dd>{selected.token.pos}</dd>
                </div>
                <div>
                  <dt>辞书形</dt>
                  <dd>{selected.token.dictForm ?? "—"}</dd>
                </div>
                <div>
                  <dt>自然度</dt>
                  <dd>
                    <NaturalnessBadge value={selected.token.naturalness} />
                  </dd>
                </div>
              </dl>

              {selected.token.flags.length > 0 && (
                <div className="flag-row">
                  {selected.token.flags.map((flag) => (
                    <span className="flag" key={flag}>
                      {FLAG_LABEL[flag]}
                    </span>
                  ))}
                </div>
              )}

              <section className="panel-section">
                <span className="panel-label">释义</span>
                {selected.token.glossZh !== null ? (
                  <p className="panel-gloss">{selected.token.glossZh}</p>
                ) : (
                  <div className="panel-missing">
                    <p>还没有中文释义。</p>
                    <button
                      type="button"
                      className="btn btn--ghost btn--small"
                      onClick={() => void runAnnotate()}
                      disabled={annotateJob.running}
                    >
                      <IconSparkle size={14} />
                      AI 注释
                    </button>
                  </div>
                )}
              </section>

              {selected.token.note !== null && (
                <section className="panel-section">
                  <span className="panel-label">备注</span>
                  <p className="panel-note">{selected.token.note}</p>
                </section>
              )}

              <section className="panel-section panel-line-card">
                <span className="panel-label">这一行</span>
                <p className="panel-line-text" lang="ja">
                  {selected.line.text}
                </p>
                {selected.line.glossZh !== null ? (
                  <p className="panel-line-gloss">{selected.line.glossZh}</p>
                ) : (
                  <p className="panel-line-gloss is-missing">还没有整行翻译</p>
                )}
                {selected.line.note !== null && (
                  <p className="panel-line-note">{selected.line.note}</p>
                )}
                {selected.line.naturalness === "red" && (
                  <p className="panel-advice">
                    这行只出现在歌词里，日常会话可以换成更自然的说法。
                  </p>
                )}
              </section>

              <div className="panel-actions">
                <button
                  type="button"
                  className={cn("btn", selected.token.saved ? "btn--saved" : "btn--primary")}
                  onClick={() => void toggleCard()}
                  disabled={busy}
                  title={selected.token.saved ? "点击移出复习卡" : "存为复习卡片"}
                >
                  {selected.token.saved ? (
                    <>
                      <IconCheck size={16} /> 已存入复习
                    </>
                  ) : (
                    <>
                      <IconBookmark size={16} /> 加入复习
                    </>
                  )}
                </button>
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={startReading}
                  disabled={busy}
                >
                  改读音
                </button>
              </div>

              {reading !== null && (
                <form className="reading-form" onSubmit={submitReading}>
                  <label className="panel-label" htmlFor={`reading-${selected.token.id}`}>
                    改读音
                  </label>
                  <div className="reading-row">
                    <input
                      id={`reading-${selected.token.id}`}
                      className="reading-input"
                      value={reading}
                      onChange={(event) => setReading(event.target.value)}
                      lang="ja"
                      autoFocus
                      spellCheck={false}
                    />
                    <button type="submit" className="btn btn--primary btn--small" disabled={busy}>
                      保存
                    </button>
                    <button
                      type="button"
                      className="btn btn--ghost btn--small"
                      onClick={() => setReading(null)}
                    >
                      取消
                    </button>
                  </div>
                  <p className="field-hint">平假名或片假名均可，保存后罗马音与音拍会重新计算。</p>
                  {readingError !== null && (
                    <p className="form-error" role="alert">
                      {readingError}
                    </p>
                  )}
                </form>
              )}

              <p className="panel-foot">存成卡片后，会带原唱片段出现在「覚える」里。</p>
            </div>
          )}
        </aside>
      </div>
    </main>
  );
}
