import type { SizeMode } from "../lib/persist";
import { L } from "../labels";

const ORDER: SizeMode[] = ["s", "m", "l"];

/** Three-step scale for thumbnails: small / medium / large. */
export function SizePicker({ value, onChange }: { value: SizeMode; onChange: (v: SizeMode) => void }) {
  return (
    <div role="group" aria-label={L.sizeLabel} style={{ display: "flex", gap: 4, alignItems: "center" }}>
      <span style={{ color: "var(--fg2)", fontSize: 12, marginRight: 4 }}>{L.sizeLabel}</span>
      {ORDER.map((v) => {
        const active = v === value;
        return (
          <button
            key={v}
            onClick={() => onChange(v)}
            aria-pressed={active}
            style={{
              width: 30, height: 26, borderRadius: 6, cursor: "pointer", fontSize: 12,
              background: "transparent", color: active ? "var(--accent)" : "var(--fg2)",
              border: active ? "2px solid var(--accent)" : "1px solid var(--border)",
            }}
          >
            {L.sizeNames[v]}
          </button>
        );
      })}
    </div>
  );
}
