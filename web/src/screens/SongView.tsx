import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { deleteSong, getSong, listSongs } from "../api";
import type { Song } from "../types";
import { Brand } from "../components/Brand";
import { Boot } from "../components/Boot";
import { ModeBanner } from "../components/ModeBanner";
import { SongCover } from "../components/SongCover";
import { useToast } from "../components/Toast";
import { useRuntimeMode } from "../hooks/useRuntimeMode";
import { IconBack, IconRefresh, IconTrash } from "../components/Icons";
import { cn } from "../lib/cn";
import { toMessage } from "../lib/errors";
import { Karaoke } from "./Karaoke";
import { LyricsPaste } from "./LyricsPaste";
import { Review } from "./Review";
import { Study } from "./Study";

const TABS = [
  { key: "karaoke", label: "歌う", hint: "跟唱" },
  { key: "study", label: "読む", hint: "读懂" },
  { key: "review", label: "覚える", hint: "记住" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

function parseTab(value: string | null): TabKey {
  if (value === "study" || value === "review") return value;
  return "karaoke";
}

function isSynced(song: Song): boolean {
  return song.lines.length > 0 && song.lines.every((line) => line.start >= 0);
}

export function SongView() {
  const { id } = useParams<{ id: string }>();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { toast } = useToast();
  const mode = useRuntimeMode();
  const tab = parseTab(params.get("tab"));

  const [song, setSong] = useState<Song | null>(null);
  const [hue, setHue] = useState(338);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(
    async (showSpinner = true) => {
      if (id === undefined) {
        setError("没有指定歌曲。");
        setLoading(false);
        return;
      }
      if (showSpinner) {
        setLoading(true);
        setSong(null);
      }
      setError(null);
      try {
        const [loaded, summaries] = await Promise.all([
          getSong(id),
          listSongs().catch(() => []),
        ]);
        setSong(loaded);
        const summary = summaries.find((item) => item.id === loaded.id);
        if (summary !== undefined) setHue(summary.thumbHue);
      } catch (unknownError) {
        setError(toMessage(unknownError));
      } finally {
        setLoading(false);
      }
    },
    [id],
  );

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (song === null) return;
    document.title = `${song.title} · Mora モーラ`;
    return () => {
      document.title = "Mora モーラ · 跟唱日文歌";
    };
  }, [song]);

  const setTab = (key: TabKey) => {
    const next = new URLSearchParams(params);
    if (key === "karaoke") next.delete("tab");
    else next.set("tab", key);
    setParams(next, { replace: true });
  };

  const handleDelete = async () => {
    if (song === null || deleting) return;
    setDeleting(true);
    try {
      await deleteSong(song.id);
      toast("已删除这首歌");
      navigate("/");
    } catch (unknownError) {
      toast(toMessage(unknownError), "error");
      setDeleting(false);
      setConfirmDelete(false);
    }
  };

  if (loading) {
    return (
      <div className="song-shell">
        <Boot text="正在打开歌曲…" />
      </div>
    );
  }

  if (error !== null || song === null) {
    return (
      <div className="song-shell">
        <ModeBanner />
        <div className="state-shell">
          <Brand />
          <p className="state-title">这首歌打不开了</p>
          <p className="state-text">{error ?? "找不到这首歌。"}</p>
          <div className="review-empty-actions">
            <Link className="btn btn--ghost" to="/">
              <IconBack size={16} />
              返回曲库
            </Link>
            <button type="button" className="btn btn--primary" onClick={() => void load()}>
              <IconRefresh size={16} />
              重试
            </button>
          </div>
        </div>
      </div>
    );
  }

  const synced = isSynced(song);

  return (
    <div className="song-shell">
      <ModeBanner />
      <header className="song-head">
        <div className="song-head-left">
          <Link to="/" className="icon-btn" aria-label="返回曲库">
            <IconBack size={19} />
          </Link>
          <SongCover title={song.title} hue={hue} size="sm" />
          <div className="song-title-wrap">
            <h1>{song.title}</h1>
            <p>{song.artist}</p>
          </div>
        </div>

        <nav className="tabs" aria-label="视图">
          {TABS.map((item) => (
            <button
              key={item.key}
              type="button"
              className={cn("tab", tab === item.key && "is-active")}
              onClick={() => setTab(item.key)}
              aria-current={tab === item.key ? "page" : undefined}
            >
              <span className="tab-label" lang="ja">
                {item.label}
              </span>
              <span className="tab-hint">{item.hint}</span>
            </button>
          ))}
        </nav>

        <div className="song-head-right">
          {mode === "mock" && <span className="demo-chip">演示模式</span>}
          <span className={cn("sync-pill", synced ? "is-synced" : "is-unsynced")}>
            {synced ? "已同步" : "未同步"}
          </span>
          <div className="delete-wrap">
            <button
              type="button"
              className="icon-btn"
              onClick={() => setConfirmDelete((previous) => !previous)}
              aria-label="删除这首歌"
              aria-expanded={confirmDelete}
            >
              <IconTrash size={18} />
            </button>
            {confirmDelete && (
              <div className="confirm-pop" role="dialog" aria-label="确认删除歌曲">
                <p>
                  删除《{song.title}》？歌词、时间轴和这张歌的复习卡都会一起删掉。
                </p>
                <div>
                  <button
                    type="button"
                    className="btn btn--ghost btn--small"
                    onClick={() => setConfirmDelete(false)}
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    className="btn btn--danger btn--small"
                    onClick={() => void handleDelete()}
                    disabled={deleting}
                  >
                    {deleting ? "删除中…" : "删除"}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </header>

      <div
        className={cn(
          "song-body",
          tab === "karaoke" && song.lines.length > 0 ? "song-body--stage" : "song-body--scroll",
        )}
      >
        {song.lines.length === 0 ? (
          <LyricsPaste song={song} onSongChange={setSong} />
        ) : tab === "karaoke" ? (
          <Karaoke song={song} onSongChange={setSong} mock={mode === "mock"} />
        ) : tab === "study" ? (
          <Study song={song} onSongChange={setSong} />
        ) : (
          <Review song={song} onGoStudy={() => setTab("study")} />
        )}
      </div>
    </div>
  );
}
