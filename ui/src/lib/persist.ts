/** Remember where the owner stopped. Local to this browser; failures are ignored on purpose. */

const LAST_STEM = "arl.lastStem";
const posKey = (stem: string) => `arl.pos.${stem}`;

export interface Position {
  clip: string;
  variant: string;
  t: number;
}

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
  lastStem: () => read<string>(LAST_STEM),
  setLastStem: (stem: string | null) => write(LAST_STEM, stem),
  position: (stem: string) => read<Position>(posKey(stem)),
  setPosition: (stem: string, pos: Position) => write(posKey(stem), pos),
};
