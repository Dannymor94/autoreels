/** Remember where the owner stopped. Local to this browser; failures are ignored on purpose. */

const LAST_ROUTE = "arl.lastRoute";
const VIEW = "arl.view";
const SIZE = "arl.size";
const posKey = (stem: string) => `arl.pos.${stem}`;

export interface Position {
  clip: string;
  variant: string;
  t: number;
}

export type ViewMode = "grid" | "list";

/** Thumbnail scale for lists and grids. One setting for the whole app. */
export type SizeMode = "s" | "m" | "l";

function read<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function write(key: string, value: unknown): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage full or disabled — not important */
  }
}

export const persist = {
  lastRoute: () => read<string>(LAST_ROUTE),
  setLastRoute: (hash: string) => write(LAST_ROUTE, hash),
  view: (): ViewMode => (read<ViewMode>(VIEW) === "list" ? "list" : "grid"),
  setView: (v: ViewMode) => write(VIEW, v),
  size: (): SizeMode => {
    const v = read<SizeMode>(SIZE);
    return v === "m" || v === "l" ? v : "s";
  },
  setSize: (v: SizeMode) => write(SIZE, v),
  position: (stem: string) => read<Position>(posKey(stem)),
  setPosition: (stem: string, pos: Position) => write(posKey(stem), pos),
};
