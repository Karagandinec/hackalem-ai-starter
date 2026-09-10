import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { getHealth, type Health } from "../api";

/** Пункты меню. Добавляешь страницу — добавляешь строку сюда и <Route> в App.tsx. */
const NAV = [
  { to: "/", label: "Дашборд", icon: "▦" },
  { to: "/entities", label: "Данные", icon: "☰" },
  { to: "/chat", label: "Ассистент", icon: "✦" },
  { to: "/ai-metrics", label: "AI-метрики", icon: "◷" },
];

export default function Layout({ children }: { children: React.ReactNode }) {
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealth({ status: "offline" }));
  }, []);

  const dotClass = health === null ? "off" : health.status === "ok" ? "ok" : "err";

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="logo">
          Hack<span>Alem</span>
        </div>

        <nav className="nav">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === "/"}>
              <span aria-hidden>{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div>
            <span className={`dot ${dotClass}`} />
            {health === null ? "проверяю..." : health.status === "ok" ? "backend на связи" : "backend недоступен"}
          </div>
          {health?.ai_enabled === false && <div>⚠ AI в режиме заглушки</div>}
          {health?.model && <div className="mono">{health.model}</div>}
        </div>
      </aside>

      <main className="content">{children}</main>
    </div>
  );
}
