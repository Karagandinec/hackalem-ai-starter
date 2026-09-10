import { useEffect, useState } from "react";

import { getEntities, type Entity } from "../api";
import { formatNumber } from "./MetricCard";

/**
 * Таблица с фильтрами: период дат, статус, поиск по названию.
 * Фильтрует бэкенд (GET /api/entities), фронт только собирает параметры —
 * так таблица не ломается на больших объёмах.
 */
export default function DataTable({ defaultDays = 30, limit = 50 }: { defaultDays?: number; limit?: number }) {
  const [dateFrom, setDateFrom] = useState(daysAgo(defaultDays));
  const [dateTo, setDateTo] = useState(daysAgo(0));
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [rows, setRows] = useState<Entity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getEntities({ date_from: dateFrom, date_to: dateTo, status, search, limit })
      .then((data) => {
        if (!cancelled) {
          setRows(data);
          setError(null);
        }
      })
      .catch((err: Error) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [dateFrom, dateTo, status, search, limit]);

  return (
    <div className="card">
      <h2>Записи</h2>

      <div className="filters">
        <div className="field">
          <label htmlFor="date-from">Дата с</label>
          <input id="date-from" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="date-to">Дата по</label>
          <input id="date-to" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="status">Статус</label>
          <select id="status" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">все</option>
            <option value="new">new</option>
            <option value="in_progress">in_progress</option>
            <option value="done">done</option>
            <option value="cancelled">cancelled</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="search">Поиск</label>
          <input
            id="search"
            placeholder="по названию"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <button
          className="ghost"
          onClick={() => {
            setDateFrom(daysAgo(defaultDays));
            setDateTo(daysAgo(0));
            setStatus("");
            setSearch("");
          }}
        >
          Сбросить
        </button>
      </div>

      {error && <div className="error-box">Не удалось загрузить: {error}</div>}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Название</th>
              <th>Тип</th>
              <th>Статус</th>
              <th>Категория</th>
              <th>Город</th>
              <th className="num">Сумма</th>
              <th>Создано</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td className="muted mono">{row.id}</td>
                <td>{row.name}</td>
                <td className="muted">{row.type}</td>
                <td>
                  <span className={`badge ${row.status}`}>{row.status}</span>
                </td>
                <td className="muted">{row.category ?? "—"}</td>
                <td className="muted">{row.city ?? "—"}</td>
                <td className="num">{formatNumber(row.amount)}</td>
                <td className="muted mono">{row.created_at.slice(0, 16).replace("T", " ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="muted" style={{ marginTop: 12, fontSize: 12 }}>
        {loading ? "Загружаю..." : `Показано ${rows.length} записей (лимит ${limit})`}
      </div>
    </div>
  );
}

function daysAgo(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
}
