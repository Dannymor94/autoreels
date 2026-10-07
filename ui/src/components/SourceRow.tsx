import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type SourceItem } from "../api/client";
import { L } from "../labels";

interface Props {
  source: SourceItem;
  onOpen: () => void;
}

/** One source: thumbnail, display name (editable), folder name, counts. */
export function SourceRow({ source: s, onOpen }: Props) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const rename = useMutation({
    mutationFn: (name: string | null) => api.renameSource(s.stem, name),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }),
  });

  const start = () => {
    setDraft(s.display_name ?? s.stem);
    setEditing(true);
  };
  const save = () => {
    setEditing(false);
    const v = draft.trim();
    rename.mutate(v === "" || v === s.stem ? null : v);
  };

  return (
    <li
      style={{
        display: "flex", alignItems: "center", gap: 14, padding: 8,
        background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: "var(--radius)",
      }}
    >
      <button onClick={onOpen} aria-label={s.display_name ?? s.stem} style={{ border: "none", padding: 0, background: "none", cursor: "pointer" }}>
        <div style={{ width: 54, height: 96, background: "#000", borderRadius: 6, overflow: "hidden" }}>
          {s.poster_clip && (
            <img
              src={api.thumbUrl(s.stem, s.poster_clip, s.poster_variant)}
              alt=""
              loading="lazy"
              style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
              onError={(e) => ((e.target as HTMLImageElement).style.visibility = "hidden")}
            />
          )}
        </div>
      </button>

      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 4 }}>
        {editing ? (
          <>
            <input
              autoFocus
              value={draft}
              maxLength={120}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") save();
                if (e.key === "Escape") setEditing(false);
              }}
              onBlur={save}
              style={{ fontSize: 16, padding: "4px 8px", background: "var(--bg)", color: "var(--fg)", border: "1px solid var(--accent)", borderRadius: 6 }}
            />
            <span style={{ color: "var(--fg2)", fontSize: 12 }}>{L.renameHint}</span>
          </>
        ) : (
          <button
            onClick={onOpen}
            style={{ textAlign: "left", background: "none", border: "none", padding: 0, cursor: "pointer", color: "var(--fg)", fontSize: 16 }}
          >
            {s.display_name ?? s.stem}
          </button>
        )}
        {s.display_name && <span style={{ color: "var(--fg2)", fontSize: 12 }}>{L.folder(s.stem)}</span>}
      </div>

      <span style={{ color: "var(--fg2)", fontSize: 13, whiteSpace: "nowrap" }}>
        {L.clipCount(s.clip_count)}{L.variantsCount(s.variant_names.length)}
      </span>
      {!editing && (
        <button
          onClick={start}
          title={L.rename}
          aria-label={L.rename}
          style={{ background: "none", border: "1px solid var(--border)", borderRadius: 6, color: "var(--fg2)", cursor: "pointer", padding: "4px 8px" }}
        >
          ✎
        </button>
      )}
    </li>
  );
}
