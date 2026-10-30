import type { ClipItem } from "../api/client";

/** One clip id (r01) with all variants that exist for it. "" = main render, always first. */
export interface ClipGroup {
  clip: string;
  variants: string[];
  /** Facts (title, duration) of the first variant — the main render when it exists. */
  info: ClipItem;
}

export function groupClips(items: ClipItem[]): ClipGroup[] {
  const map = new Map<string, ClipItem[]>();
  for (const it of items) {
    if (!map.has(it.clip)) map.set(it.clip, []);
    map.get(it.clip)!.push(it);
  }
  return [...map.keys()].sort().map((clip) => {
    const list = map.get(clip)!.sort((a, b) =>
      a.variant === "" ? -1 : b.variant === "" ? 1 : a.variant.localeCompare(b.variant),
    );
    return { clip, variants: list.map((x) => x.variant), info: list[0] };
  });
}

/** "_gate/montage" → "montage"; "" → null (caller shows the "main" label). */
export function variantShortName(variant: string): string | null {
  return variant === "" ? null : variant.replace(/^_gate\//, "");
}

/** Keep the current variant when moving to another clip if that clip has it, else main. */
export function pickVariant(group: ClipGroup, wanted: string): string {
  return group.variants.includes(wanted) ? wanted : group.variants[0];
}

/** 37.6 → "0:38"; null → "—". */
export function formatDuration(s: number | null | undefined): string {
  if (s == null) return "—";
  const r = Math.round(s);
  return `${Math.floor(r / 60)}:${String(r % 60).padStart(2, "0")}`;
}
