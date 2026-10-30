import { useEffect, useRef } from "react";
import { actionFor, type Action } from "../keys";

/** Calls handler(action) for keys from the KEYS table. Always uses the latest handler. */
export function useHotkeys(handler: (a: Action) => void): void {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const a = actionFor(e);
      if (!a) return;
      e.preventDefault();
      ref.current(a);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
