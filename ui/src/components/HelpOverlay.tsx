import { KEYS } from "../keys";
import { L } from "../labels";

export function HelpOverlay({ onClose }: { onClose: () => void }) {
  return (
    <div
      role="dialog"
      aria-label={L.help}
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 10,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--bg2)", border: "1px solid var(--border)",
          borderRadius: "var(--radius)", padding: 20, minWidth: 320,
        }}
      >
        <h3 style={{ marginBottom: 12 }}>{L.help}</h3>
        <table style={{ borderCollapse: "collapse", fontSize: 14 }}>
          <tbody>
            {KEYS.filter((k) => k.action !== "closeHelp").map((k) => (
              <tr key={k.code}>
                <td style={{ padding: "4px 16px 4px 0", fontFamily: "monospace", whiteSpace: "nowrap" }}>{k.label}</td>
                <td style={{ padding: "4px 0", color: "var(--fg2)" }}>{k.help}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <button onClick={onClose} style={{ marginTop: 16, cursor: "pointer" }}>{L.close}</button>
      </div>
    </div>
  );
}
