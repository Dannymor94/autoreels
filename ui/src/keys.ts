/**
 * The ONE table of keyboard shortcuts. The help overlay is built from it.
 * Matched by KeyboardEvent.code (physical key), so it works with the Russian layout too.
 */

export type Action =
  | "playPause"
  | "back2"
  | "fwd2"
  | "nextClip"
  | "prevClip"
  | "nextVariant"
  | "toggleHelp"
  | "escape";

export interface KeyBinding {
  code: string;
  label: string; // what the help overlay shows
  action: Action;
  help: string; // Russian description
}

export const KEYS: KeyBinding[] = [
  { code: "Space", label: "Пробел", action: "playPause", help: "пауза / воспроизведение" },
  { code: "ArrowLeft", label: "←", action: "back2", help: "назад на 2 секунды" },
  { code: "ArrowRight", label: "→", action: "fwd2", help: "вперёд на 2 секунды" },
  { code: "KeyJ", label: "J", action: "nextClip", help: "следующий клип" },
  { code: "KeyK", label: "K", action: "prevClip", help: "предыдущий клип" },
  { code: "KeyV", label: "V", action: "nextVariant", help: "следующий вариант на той же секунде" },
  { code: "Slash", label: "?", action: "toggleHelp", help: "показать / скрыть подсказку" },
  { code: "Escape", label: "Esc", action: "escape", help: "закрыть подсказку / назад к обзору" },
];

/** Returns the action for a key event, or null. Ignores typing in fields and Cmd/Ctrl/Alt combos. */
export function actionFor(e: KeyboardEvent): Action | null {
  if (e.metaKey || e.ctrlKey || e.altKey) return null;
  const t = e.target as HTMLElement | null;
  if (t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName))) return null;
  return KEYS.find((k) => k.code === e.code)?.action ?? null;
}
