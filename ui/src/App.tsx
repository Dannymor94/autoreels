import { useEffect } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TopBar } from "./components/TopBar";
import { Sources } from "./screens/Sources";
import { Overview } from "./screens/Overview";
import { Source } from "./screens/Source";
import { persist } from "./lib/persist";
import { formatRoute, navigate, useRoute } from "./lib/route";
import "./theme.css";

const queryClient = new QueryClient();

// Opening the app without an address → go back to where the owner was.
if (!location.hash || location.hash === "#") {
  const last = persist.lastRoute();
  if (last) history.replaceState(null, "", last);
}

function Router() {
  const route = useRoute();
  useEffect(() => persist.setLastRoute(formatRoute(route)), [route]);

  return (
    <>
      <TopBar />
      {route.name === "sources" && <Sources onSelect={(stem) => navigate({ name: "overview", stem })} />}
      {route.name === "overview" && (
        <Overview
          key={route.stem}
          stem={route.stem}
          onBack={() => navigate({ name: "sources" })}
          onOpen={(clip, variant) => navigate({ name: "review", stem: route.stem, clip, variant })}
        />
      )}
      {route.name === "review" && (
        <Source
          key={route.stem}
          stem={route.stem}
          initialClip={route.clip}
          initialVariant={route.variant}
          onBack={() => navigate({ name: "overview", stem: route.stem })}
          onChange={(clip, variant) => navigate({ name: "review", stem: route.stem, clip, variant }, true)}
        />
      )}
    </>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Router />
    </QueryClientProvider>
  );
}
