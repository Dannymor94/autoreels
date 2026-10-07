import type { ClipItem } from "../api/client";

/** One clip id (r01) with all variants that exist for it. "" = main render, always first. */
export interface ClipGroup {
  clip: string;
  variants: string[];
}

export function groupClips(items: ClipItem[]): ClipGroup[] {
  const map = new Map<string, Set<string>>();
  for (const it of items) {
    if (!map.has(it.clip)) map.set(it.clip, new Set());
    map.get(it.clip)!.add(it.variant);
  }
  return [...map.keys()].sort().map((clip) => ({
    clip,
    variants: [...map.get(clip)!].sort((a, b) => (a === "" ? -1 : b === "" ? 1 : a.localeCompare(b))),
  }));
}

/** "_gate/montage" → "montage"; "" → null (caller shows the "main" label). */
export function variantShortName(variant: string): string | null {
  return variant === "" ? null : variant.replace(/^_gate\//, "");
}

/** Keep the current variant when moving to another clip if that clip has it, else main. */
export function pickVariant(group: ClipGroup, wanted: string): string {
  return group.variants.includes(wanted) ? wanted : group.variants[0];
}
