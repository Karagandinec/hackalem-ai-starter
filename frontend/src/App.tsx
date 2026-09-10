import { Navigate, Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import AiMetrics from "./pages/AiMetrics";
import Chat from "./pages/Chat";
import Dashboard from "./pages/Dashboard";
import Fleet from "./pages/Fleet";

/** Роуты приложения. Новая страница = новый <Route> + пункт в Layout. */
export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/fleet" element={<Fleet />} />
        <Route path="/chat" element={<Chat />} />
        <Route path="/ai-metrics" element={<AiMetrics />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
