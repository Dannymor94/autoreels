import type { CSSProperties } from "react";
import { formatDuration, variantShortName, type ClipGroup } from "../lib/clips";
import { L } from "../labels";

interface Props {
  groups: ClipGroup[];
  onOpen: (clip: string) => void;
}

/** List view: one row per clip — fast to scan titles and durations. */
export function ClipTable({ groups, onOpen }: Props) {
  const th: CSSProperties = { textAlign: "left", padding: "6px 12px", color: "var(--fg2)", fontWeight: 500, borderBottom: "1px solid var(--border)" };
  const td: CSSProperties = { padding: "8px 12px", borderBottom: "1px solid var(--border)" };
  return (
    <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}>
      <thead>
        <tr>
          <th style={th}>{L.colClip}</th>
          <th style={th}>{L.colTitle}</th>
          <th style={th}>{L.colDuration}</th>
          <th style={th}>{L.colVariants}</th>
        </tr>
      </thead>
      <tbody>
        {groups.map((g) => (
          <tr key={g.clip} onClick={() => onOpen(g.clip)} style={{ cursor: "pointer" }}>
            <td style={td}><strong>{g.clip}</strong></td>
            <td style={td}>{g.info.title ?? "—"}</td>
            <td style={{ ...td, fontVariantNumeric: "tabular-nums" }}>{formatDuration(g.info.duration_s)}</td>
            <td style={{ ...td, color: "var(--fg2)" }}>
              {g.variants.map((v) => variantShortName(v) ?? L.mainVariant).join(", ")}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
