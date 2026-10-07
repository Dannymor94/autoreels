import type { components } from "./types.gen";

export type HealthResponse = components["schemas"]["HealthResponse"];
export type SourceItem = components["schemas"]["SourceItem"];
export type ClipItem = components["schemas"]["ClipItem"];
export type CapabilitiesResponse = components["schemas"]["CapabilitiesResponse"];

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} — ${path}`);
  return r.json() as Promise<T>;
}

export const api = {
  health: () => get<HealthResponse>("/api/health"),
  sources: () => get<SourceItem[]>("/api/sources"),
  clips: (stem: string) => get<ClipItem[]>(`/api/sources/${encodeURIComponent(stem)}/clips`),
  mediaUrl: (stem: string, clip: string, variant = "") =>
    `/api/media/${encodeURIComponent(stem)}/${encodeURIComponent(clip)}${variant ? `?variant=${encodeURIComponent(variant)}` : ""}`,
};
