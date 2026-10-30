import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { L } from "../labels";
import { formatDuration, groupClips } from "../lib/clips";
import { persist, type ViewMode } from "../lib/persist";
import { ClipCard } from "../components/ClipCard";
import { ClipTable } from "../components/ClipTable";
import { SizePicker } from "../components/SizePicker";
import { SIZES, useSize } from "../lib/size";

interface Props {
  stem: string;
  onBack: () => void;
  onOpen: (clip: string, variant: string) => void;
}

/** Level 2: every reel of one source at once — grid or list. */
export function Overview({ stem, onBack, onOpen }: Props) {
  const { data, isLoading, error } = useQuery({ queryKey: ["clips", stem], queryFn: () => api.clips(stem) });
  const sources = useQuery({ queryKey: ["sources"], queryFn: api.sources });
  const displayName = sources.data?.find((x) => x.stem === stem)?.display_name ?? null;
  const groups = useMemo(() => groupClips(data ?? []), [data]);
  const [view, setViewState] = useState<ViewMode>(() => persist.view());
  const setView = (v: ViewMode) => {
    persist.setView(v);
    setViewState(v);
  };
  const [size, setSize] = useSize();
  const pos = persist.position(stem);
  const variantCount = groups.reduce((n, g) => n + g.variants.length - 1, 0);

  const btn = (active: boolean) => ({
    padding: "4px 12px", borderRadius: "var(--radius)", cursor: "pointer", fontSize: 13,
    background: "transparent", color: active ? "var(--accent)" : "var(--fg2)",
    border: active ? "2px solid var(--accent)" : "1px solid var(--border)",
  });

  return (
    <main style={{ padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16, flexWrap: "wrap" }}>
        <button onClick={onBack} style={{ cursor: "pointer", background: "none", border: "none", color: "var(--accent)" }}>
          {L.backToSources}
        </button>
        <h2>{displayName ?? stem}</h2>
        {displayName && <span style={{ color: "var(--fg2)", fontSize: 12 }}>{L.folder(stem)}</span>}
        {groups.length > 0 && <span style={{ color: "var(--fg2)" }}>{L.overviewSummary(groups.length, variantCount)}</span>}
        <div style={{ marginLeft: "auto", display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          {view === "grid" && <SizePicker value={size} onChange={setSize} />}
          <button style={btn(view === "grid")} onClick={() => setView("grid")}>{L.viewGrid}</button>
          <button style={btn(view === "list")} onClick={() => setView("list")}>{L.viewList}</button>
          {pos && groups.some((g) => g.clip === pos.clip) && (
            <button style={btn(false)} onClick={() => onOpen(pos.clip, pos.variant)}>
              {L.continueAt(pos.clip, formatDuration(pos.t))}
            </button>
          )}
          {groups.length > 0 && (
            <button
              style={{ ...btn(false), background: "var(--accent)", color: "#fff", border: "1px solid var(--accent)" }}
              onClick={() => onOpen(groups[0].clip, "")}
            >
              {L.watchInOrder}
            </button>
          )}
        </div>
      </div>

      {isLoading && <p>{L.loading}</p>}
      {error && <p style={{ color: "red" }}>{L.error}: {String(error)}</p>}
      {!isLoading && !error && groups.length === 0 && <p>{L.noClips}</p>}

      {view === "grid" ? (
        <div style={{ display: "grid", gridTemplateColumns: `repeat(auto-fill, minmax(${SIZES[size].cardMin}px, 1fr))`, gap: 16 }}>
          {groups.map((g) => (
            <ClipCard key={g.clip} stem={stem} group={g} onOpen={() => onOpen(g.clip, g.variants[0])} />
          ))}
        </div>
      ) : (
        <ClipTable groups={groups} onOpen={(c) => onOpen(c, "")} />
      )}
    </main>
  );
}
