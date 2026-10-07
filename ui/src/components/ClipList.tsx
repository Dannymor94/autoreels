import type { ClipGroup } from "../lib/clips";
import { L } from "../labels";

interface Props {
  groups: ClipGroup[];
  current: string | null;
  onPick: (clip: string) => void;
}

export function ClipList({ groups, current, onPick }: Props) {
  return (
    <ul style={{ listStyle: "none", display: "flex", flexDirection: "column", gap: 4, minWidth: 160 }}>
      {groups.map((g) => {
        const active = g.clip === current;
        const extra = g.variants.length - 1;
        return (
          <li key={g.clip}>
            <button
              onClick={() => onPick(g.clip)}
              style={{
                width: "100%", display: "flex", justifyContent: "space-between", gap: 8,
                background: active ? "var(--accent)" : "var(--bg2)",
                color: active ? "#fff" : "var(--fg)",
                border: "1px solid var(--border)", borderRadius: "var(--radius)",
                padding: "6px 10px", cursor: "pointer", fontSize: 14,
              }}
            >
              <span>{g.clip}</span>
              {extra > 0 && <span style={{ opacity: 0.75, fontSize: 12 }}>{L.variantsMore(extra)}</span>}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
