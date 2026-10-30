import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { L } from "../labels";
import { SourceRow } from "../components/SourceRow";
import { SizePicker } from "../components/SizePicker";
import { SIZES, useSize } from "../lib/size";

interface Props {
  onSelect: (stem: string) => void;
}

export function Sources({ onSelect }: Props) {
  const { data, isLoading, error } = useQuery({ queryKey: ["sources"], queryFn: api.sources });
  const [size, setSize] = useSize();

  if (isLoading) return <p style={{ padding: 16 }}>{L.loading}</p>;
  if (error) return <p style={{ padding: 16, color: "red" }}>{L.error}: {String(error)}</p>;
  if (!data?.length) return <p style={{ padding: 16 }}>{L.noSources}</p>;

  return (
    <main style={{ padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 12 }}>
        <h2>{L.sources}</h2>
        <div style={{ marginLeft: "auto" }}>
          <SizePicker value={size} onChange={setSize} />
        </div>
      </div>
      <ul style={{ listStyle: "none", display: "flex", flexDirection: "column", gap: size === "s" ? 4 : 8 }}>
        {data.map((s) => (
          <SourceRow key={s.stem} source={s} thumbH={SIZES[size].thumbH} onOpen={() => onSelect(s.stem)} />
        ))}
      </ul>
    </main>
  );
}
