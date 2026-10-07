import { useEffect, useState } from "react";

/**
 * Three levels, each with its own address so the browser Back button works:
 *   #/                         → all sources
 *   #/s/<stem>                 → overview of one source (grid / list)
 *   #/s/<stem>/<clip>?v=<var>  → step-by-step review
 */
export type Route =
  | { name: "sources" }
  | { name: "overview"; stem: string }
  | { name: "review"; stem: string; clip: string; variant: string };

export function parseRoute(hash: string): Route {
  const [path, query = ""] = hash.replace(/^#/, "").split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] === "s" && parts[1]) {
    if (parts[2]) {
      const v = new URLSearchParams(query).get("v") ?? "";
      return { name: "review", stem: parts[1], clip: parts[2], variant: v };
    }
    return { name: "overview", stem: parts[1] };
  }
  return { name: "sources" };
}

export function formatRoute(r: Route): string {
  if (r.name === "sources") return "#/";
  const base = `#/s/${encodeURIComponent(r.stem)}`;
  if (r.name === "overview") return base;
  const q = r.variant ? `?v=${encodeURIComponent(r.variant)}` : "";
  return `${base}/${encodeURIComponent(r.clip)}${q}`;
}

/** replace=true changes the address without adding a Back-button step (used for J/K/V). */
export function navigate(r: Route, replace = false): void {
  const hash = formatRoute(r);
  if (replace) history.replaceState(null, "", hash);
  else location.hash = hash;
  if (replace) window.dispatchEvent(new HashChangeEvent("hashchange"));
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseRoute(location.hash));
  useEffect(() => {
    const on = () => setRoute(parseRoute(location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}
