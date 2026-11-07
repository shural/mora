import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ingest, listSongs } from "../api";
import { Brand } from "../components/Brand";
import { IconChevronRight, IconMusic, IconRefresh } from "../components/Icons";
import { JobProgress } from "../components/JobProgress";
import { ModeBanner } from "../components/ModeBanner";
import { SongCover } from "../components/SongCover";
import { useToast } from "../components/Toast";
import { useJobPoller } from "../hooks/useJobPoller";
import { useRuntimeMode } from "../hooks/useRuntimeMode";
import { toMessage } from "../lib/errors";
import { formatTime } from "../lib/format";
import { jobSongId, type SongSummary } from "../types";

const EMPTY_STEPS = [
  {
    title: "粘贴链接",
    text: "YouTube 或 Bilibili 的歌曲地址，也可以直接输入歌名搜索。",
  },
  {
    title: "分词与注音",
    text: "每个词都会得到假名、罗马音、词性和中文释义，还能标记这句话有多自然。",
  },
  {
    title: "跟唱与复习",
    text: "逐字高亮跟唱、打点对齐时间，再把不会的词做成卡片，用原唱片段复习。",
  },
];

export function Library() {
  const [songs, setSongs] = useState<SongSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const job = useJobPoller();
  const mode = useRuntimeMode();
  const { toast } = useToast();
  const navigate = useNavigate();

  const load = useCallback(async (showSpinner = true) => {
    if (showSpinner) setLoading(true);
    setError(null);
    try {
      const list = await listSongs();
      setSongs(list);
    } catch (unknownError) {
      setError(toMessage(unknownError));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleAdd = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = query.trim();
    if (trimmed === "" || job.running) return;
    const result = await job.run(() => ingest(trimmed));
    if (result === null) return;
    setQuery("");
    await load(false);
    const songId = jobSongId(result);
    toast(mode === "mock" ? "演示模式：已载入示例曲目" : "已添加歌曲", "success");
    if (songId !== null) navigate(`/song/${songId}`);
  };

  return (
    <div className="page page--library">
      <ModeBanner />
      <header className="page-head">
        <Brand />
        <div className="page-head-right">
          {mode === "mock" && (
            <span className="demo-chip" title="使用本地示例数据，不连接后端">
              <span className="demo-dot" aria-hidden="true" />
              演示模式
            </span>
          )}
        </div>
      </header>

      <section className="hero">
        <p className="eyebrow">本机 · 日语歌曲学习</p>
        <h1 className="hero-title">
          把想唱的日文歌，
          <br />
          <em>唱对</em>，也读懂。
        </h1>
        <p className="hero-lede">
          贴一个链接，跟着歌词逐字高亮唱；点开任何一个词，看清它的读音、语气和中文意思。
        </p>

        <form className="add-bar" onSubmit={handleAdd}>
          <IconMusic size={18} className="add-icon" />
          <input
            className="add-input"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="粘贴 YouTube / Bilibili 链接，或输入歌名"
            aria-label="粘贴链接或输入歌名"
            autoComplete="off"
            spellCheck={false}
          />
          <button
            type="submit"
            className="btn btn--primary"
            disabled={query.trim() === "" || job.running}
          >
            {job.running ? "添加中…" : "添加"}
          </button>
        </form>
        <div className="add-meta">
          全部在本机处理，音频不上传
          <span className="meta-sep" aria-hidden="true" />
          <kbd>Enter</kbd> 添加
          {mode === "mock" && (
            <>
              <span className="meta-sep" aria-hidden="true" />
              演示模式不会真的下载
            </>
          )}
        </div>
        <div className="job-slot">
          <JobProgress job={job.job} error={job.error} running={job.running} label="添加歌曲" />
        </div>
      </section>

      <section className="library" aria-busy={loading}>
        <div className="section-head">
          <span className="eyebrow">曲库</span>
          <span className="section-count">{songs.length.toString().padStart(2, "0")}</span>
        </div>

        {loading && (
          <div className="song-list" aria-hidden="true">
            {[0, 1, 2].map((index) => (
              <div className="song-row song-row--skeleton" key={index}>
                <span className="sk sk--cover" />
                <div className="sk-lines">
                  <span className="sk sk--title" />
                  <span className="sk sk--sub" />
                </div>
                <span className="sk sk--meta" />
              </div>
            ))}
          </div>
        )}

        {!loading && error !== null && (
          <div className="state-panel" role="alert">
            <p className="state-title">曲库加载失败</p>
            <p className="state-text">{error}</p>
            <button type="button" className="btn btn--ghost" onClick={() => void load()}>
              <IconRefresh size={16} />
              重试
            </button>
          </div>
        )}

        {!loading && error === null && songs.length === 0 && (
          <div className="library-empty">
            <p className="empty-title">曲库还是空的</p>
            <p className="empty-lede">从上面粘一首歌开始，三步就能跟唱。</p>
            <ol className="steps">
              {EMPTY_STEPS.map((step, index) => (
                <li className="step" key={step.title}>
                  <span className="step-num">{String(index + 1).padStart(2, "0")}</span>
                  <div>
                    <h3 className="step-title">{step.title}</h3>
                    <p className="step-text">{step.text}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        )}

        {!loading && error === null && songs.length > 0 && (
          <div className="song-list">
            {songs.map((song) => (
              <Link className="song-row" to={`/song/${song.id}`} key={song.id}>
                <SongCover title={song.title} hue={song.thumbHue} size="sm" />
                <div className="song-main">
                  <h3 className="song-title">{song.title}</h3>
                  <p className="song-artist">{song.artist}</p>
                </div>
                <div className="song-meta">
                  <span>{formatTime(song.duration)}</span>
                  <span className="meta-dot" aria-hidden="true" />
                  <span>{song.linesTotal} 行</span>
                  <span className="meta-dot" aria-hidden="true" />
                  <span>{song.cards} 张卡</span>
                  <span
                    className={song.synced ? "sync-state is-synced" : "sync-state is-unsynced"}
                  >
                    {song.synced ? "已同步" : "未同步"}
                  </span>
                </div>
                <span className="song-go" aria-hidden="true">
                  <IconChevronRight size={18} />
                </span>
              </Link>
            ))}
          </div>
        )}
      </section>

      <footer className="page-footer">
        <span>モーラ v1</span>
        <span className="meta-dot" aria-hidden="true" />
        <span>歌词跟随、分词注解、卡片复习，都在这一台 Mac 上</span>
      </footer>
    </div>
  );
}
