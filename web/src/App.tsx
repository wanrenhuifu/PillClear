import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Header } from "./components/ui/Header";
import { TabBar } from "./components/ui/TabBar";
import { ChatView } from "./features/chat/ChatView";
import { MedboxPanel } from "./features/medbox/MedboxPanel";
import { ReminderPanel } from "./features/reminder/ReminderPanel";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1 } },
});

/** 路由与布局(导出供测试以 MemoryRouter 包裹)。 */
export function AppRoutes() {
  return (
    <div className="min-h-dvh bg-paper bg-dosage-grid font-body text-ink">
      <Header />
      <div className="mx-auto flex w-full max-w-6xl gap-8 px-4 pb-28 pt-6 lg:pb-12">
        <main className="min-w-0 flex-1">
          <Routes>
            <Route path="/" element={<Navigate to="/chat" replace />} />
            <Route path="/chat" element={<ChatView />} />
            <Route path="/medbox" element={<MedboxPanel variant="full" />} />
            <Route path="/reminders" element={<ReminderPanel />} />
          </Routes>
        </main>
        <aside className="hidden w-80 shrink-0 lg:block">
          <div className="sticky top-6 rounded-xl border border-line bg-card p-4 shadow-sm">
            <MedboxPanel variant="rail" />
          </div>
        </aside>
      </div>
      <TabBar />
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
