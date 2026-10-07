import type { components } from "./types.gen";

export type HealthResponse = components["schemas"]["HealthResponse"];
export type SourceItem = components["schemas"]["SourceItem"];
export type ClipItem = components["schemas"]["ClipItem"];
export type CapabilitiesResponse = components["schemas"]["CapabilitiesResponse"];
export type SourceMetaOut = components["schemas"]["SourceMetaOut"];

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} — ${path}`);
  return r.json() as Promise<T>;
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} — ${path}`);
  return r.json() as Promise<T>;
}

export const api = {
  health: () => get<HealthResponse>("/api/health"),
  sources: () => get<SourceItem[]>("/api/sources"),
  renameSource: (stem: string, displayName: string | null) =>
    put<SourceMetaOut>(`/api/sources/${encodeURIComponent(stem)}/meta`, { display_name: displayName }),
  clips: (stem: string) => get<ClipItem[]>(`/api/sources/${encodeURIComponent(stem)}/clips`),
  thumbUrl: (stem: string, clip: string, variant = "") =>
    `/api/thumb/${encodeURIComponent(stem)}/${encodeURIComponent(clip)}${variant ? `?variant=${encodeURIComponent(variant)}` : ""}`,
  mediaUrl: (stem: string, clip: string, variant = "") =>
    `/api/media/${encodeURIComponent(stem)}/${encodeURIComponent(clip)}${variant ? `?variant=${encodeURIComponent(variant)}` : ""}`,
};
