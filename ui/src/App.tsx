import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TopBar } from "./components/TopBar";
import { Sources } from "./screens/Sources";
import { Source } from "./screens/Source";
import { persist } from "./lib/persist";
import "./theme.css";

const queryClient = new QueryClient();

function Router() {
  const [stem, setStemState] = useState<string | null>(() => persist.lastStem());
  const setStem = (s: string | null) => {
    persist.setLastStem(s);
    setStemState(s);
  };

  return (
    <>
      <TopBar />
      {stem ? (
        <Source stem={stem} onBack={() => setStem(null)} />
      ) : (
        <Sources onSelect={setStem} />
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
