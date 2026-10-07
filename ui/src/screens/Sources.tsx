import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { L } from "../labels";
import { SourceRow } from "../components/SourceRow";

interface Props {
  onSelect: (stem: string) => void;
}

export function Sources({ onSelect }: Props) {
  const { data, isLoading, error } = useQuery({ queryKey: ["sources"], queryFn: api.sources });

  if (isLoading) return <p style={{ padding: 16 }}>{L.loading}</p>;
  if (error) return <p style={{ padding: 16, color: "red" }}>{L.error}: {String(error)}</p>;
  if (!data?.length) return <p style={{ padding: 16 }}>{L.noSources}</p>;

  return (
    <main style={{ padding: 16 }}>
      <h2 style={{ marginBottom: 12 }}>{L.sources}</h2>
      <ul style={{ listStyle: "none", display: "flex", flexDirection: "column", gap: 8 }}>
        {data.map((s) => (
          <SourceRow key={s.stem} source={s} onOpen={() => onSelect(s.stem)} />
        ))}
      </ul>
    </main>
  );
}
