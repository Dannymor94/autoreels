import type { components } from "./types.gen";

export type HealthResponse = components["schemas"]["HealthResponse"];
export type JobInventory = components["schemas"]["JobInventory"];
export type SyntheticJob = components["schemas"]["SyntheticJob"];
export type JobCommand = components["schemas"]["JobCommand"];
export type RenderInventory = components["schemas"]["RenderInventory"];
export type PipelineSettings = components["schemas"]["PipelineSettings"];
export type RenderProfile = NonNullable<PipelineSettings["draft_profile"]>;
export type RenderMode = components["schemas"]["RenderMode"];
export type SourceItem = components["schemas"]["SourceItem"];
export type ProjectItem = components["schemas"]["ProjectItem"];
export type ReviewState = components["schemas"]["ReviewState"];
export type ReviewInput = components["schemas"]["ReviewInput"];
export type ComparisonInput = components["schemas"]["ComparisonInput"];
export type ComparisonState = components["schemas"]["ComparisonState"];
export type ClipItem = components["schemas"]["ClipItem"];
export type CapabilitiesResponse = components["schemas"]["CapabilitiesResponse"];
export type SourceMetaOut = components["schemas"]["SourceMetaOut"];

async function get<T>(path: string, noStore = false): Promise<T> {
  const r = await fetch(path, noStore ? { cache: "no-store" } : undefined);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} — ${path}`);
  return r.json() as Promise<T>;
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} — ${path}`);
  return r.json() as Promise<T>;
}

function reviewUrl(stem: string, clip: string, variant: string) {
  return `/api/reviews/${encodeURIComponent(stem)}/${encodeURIComponent(clip)}?variant=${encodeURIComponent(variant)}`;
}

function comparisonUrl(stem: string, clip: string, left: string, right: string) {
  return `/api/comparisons/${encodeURIComponent(stem)}/${encodeURIComponent(clip)}?${new URLSearchParams({left, right})}`;
}

export const api = {
  comparison: (stem: string, clip: string, left: string, right: string) =>
    get<ComparisonState>(comparisonUrl(stem, clip, left, right), true),
  saveComparison: (stem: string, clip: string, left: string, right: string, body: ComparisonInput) =>
    put<ComparisonState>(comparisonUrl(stem, clip, left, right), body),
  health: () => get<HealthResponse>("/api/health"),
  jobs: () => get<JobInventory>("/api/jobs", true),
  jobCommand: (id: string, command: JobCommand) => put<SyntheticJob>("/api/jobs/" + encodeURIComponent(id), command),
  renderTargets: () => get<RenderInventory>("/api/render-targets", true),
  pipelineSettings: (clips?: number, profile?: RenderProfile) => {
    const q = new URLSearchParams();
    if (clips !== undefined) q.set("clips", String(clips));
    if (profile !== undefined) q.set("profile", profile);
    return get<PipelineSettings>("/api/pipeline-settings" + (q.size ? "?" + q : ""), true);
  },
  sources: () => get<SourceItem[]>("/api/sources"),
  projects: () => get<ProjectItem[]>("/api/projects"),
  renameSource: (stem: string, displayName: string | null) =>
    put<SourceMetaOut>(`/api/sources/${encodeURIComponent(stem)}/meta`, { display_name: displayName }),
  clips: (stem: string) => get<ClipItem[]>(`/api/sources/${encodeURIComponent(stem)}/clips`),
  thumbUrl: (stem: string, clip: string, variant = "") =>
    `/api/thumb/${encodeURIComponent(stem)}/${encodeURIComponent(clip)}${variant ? `?variant=${encodeURIComponent(variant)}` : ""}`,
  review: (stem: string, clip: string, variant: string) =>
    get<ReviewState>(reviewUrl(stem, clip, variant), true),
  saveReview: (stem: string, clip: string, variant: string, body: ReviewInput) =>
    put<ReviewState>(reviewUrl(stem, clip, variant), body),
  mediaUrl: (stem: string, clip: string, variant = "", artifact?: string) => {
    const params = new URLSearchParams();
    if (variant) params.set("variant", variant);
    if (artifact) params.set("artifact", artifact);
    const query = params.toString();
    return `/api/media/${encodeURIComponent(stem)}/${encodeURIComponent(clip)}${query ? "?" + query : ""}`;
  },
};
