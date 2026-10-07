import { variantShortName } from "../lib/clips";
import { L } from "../labels";

interface Props {
  variants: string[];
  current: string;
  onPick: (variant: string) => void;
}

export function VariantTabs({ variants, current, onPick }: Props) {
  return (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
      {variants.map((v) => {
        const active = v === current;
        return (
          <button
            key={v || "main"}
            onClick={() => onPick(v)}
            style={{
              padding: "4px 12px", borderRadius: "var(--radius)", cursor: "pointer", fontSize: 13,
              background: "transparent", color: active ? "var(--accent)" : "var(--fg2)",
              border: active ? "2px solid var(--accent)" : "1px solid var(--border)",
            }}
          >
            {variantShortName(v) ?? L.mainVariant}
          </button>
        );
      })}
    </div>
  );
}
