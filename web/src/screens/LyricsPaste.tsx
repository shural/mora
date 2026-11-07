import { useState, type FormEvent } from "react";
import { postLyrics } from "../api";
import { useToast } from "../components/Toast";
import { useRuntimeMode } from "../hooks/useRuntimeMode";
import { toMessage } from "../lib/errors";
import type { Song } from "../types";

const PLACEHOLDER = `一行一句歌词，例如：

兎追いしかの山
小鮒釣りしかの川
夢は今もめぐりて`;

/** Empty-song state: paste lyrics, the backend re-tokenizes and keeps timings. */
export function LyricsPaste({
  song,
  onSongChange,
}: {
  song: Song;
  onSongChange: (song: Song) => void;
}) {
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { toast } = useToast();
  const mode = useRuntimeMode();
  const mock = mode === "mock";
  const lineCount = text.split(/\r?\n/).filter((line) => line.trim() !== "").length;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (mock) {
      setError("演示模式没有分词器；连接后端后就能粘贴歌词了。");
      return;
    }
    if (text.trim() === "") {
      setError("先粘贴歌词再保存。");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await postLyrics(song.id, text);
      onSongChange(updated);
      toast("歌词已保存并分词", "success");
    } catch (unknownError) {
      setError(toMessage(unknownError));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="paste-wrap">
      <form className="paste-panel" onSubmit={submit}>
        <p className="eyebrow">这首歌还没有歌词</p>
        <h2 className="paste-title">把歌词粘进来</h2>
        <p className="paste-lede">
          一行一句。后端会切词、标假名和罗马音；如果行数和已有时间轴一致，时间会保留。
        </p>
        <textarea
          className="paste-area"
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder={PLACEHOLDER}
          rows={10}
          spellCheck={false}
          aria-label="歌词"
        />
        <div className="paste-foot">
          <span className="paste-count">
            {lineCount > 0 ? `${lineCount} 行` : "空"}
            {mock && " · 演示模式已预置示例歌词"}
          </span>
          <button type="submit" className="btn btn--primary" disabled={saving}>
            {saving ? "正在分词…" : "保存歌词并分词"}
          </button>
        </div>
        {error !== null && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </form>
    </div>
  );
}
