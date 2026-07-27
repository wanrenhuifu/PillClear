import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <div className="min-h-dvh bg-paper bg-dosage-grid font-body text-ink">
          <header className="border-b border-line bg-card px-4 py-3.5 font-display text-lg font-bold">
            PillClear
          </header>
          <main className="p-4 text-sm text-mute">脚手架就绪。</main>
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
