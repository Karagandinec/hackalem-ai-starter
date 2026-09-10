import { useEffect, useRef, useState } from "react";

import {
  enrichEntities,
  exportCsvUrl,
  getEntities,
  importEntities,
  type Entity,
  type EntityFilters,
} from "../api";
import { formatNumber } from "./MetricCard";

/**
 * Таблица с фильтрами: период дат, статус, поиск по названию.
 * Фильтрует бэкенд (GET /api/entities), фронт только собирает параметры —
 * так таблица не ломается на больших объёмах.
 *
 * showActions=true добавляет панель «импорт CSV / разметить моделью / выгрузка».
 * На дашборде она не нужна, на странице данных — нужна.
 */
export default function DataTable({
  defaultDays = 30,
  limit = 50,
  showActions = false,
}: {
  defaultDays?: number;
  limit?: number;
  showActions?: boolean;
}) {
  const [dateFrom, setDateFrom] = useState(daysAgo(defaultDays));
  const [dateTo, setDateTo] = useState(daysAgo(0));
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [rows, setRows] = useState<Entity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState(0); // счётчик перезагрузок после действий
  const fileRef = useRef<HTMLInputElement>(null);

  const filters: EntityFilters = { date_from: dateFrom, date_to: dateTo, status, search, limit };

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
  }, [dateFrom, dateTo, status, search, limit, version]);

  async function handleImport(file: File) {
    setBusy(true);
    setNotice(null);
    try {
      const result = await importEntities(file);
      const details = result.errors.length ? ` Ошибки: ${result.errors.join("; ")}` : "";
      setNotice(
        `Загружено ${result.imported}, пропущено ${result.skipped}. ` +
          `Колонки: ${result.columns_used.join(", ") || "—"}.${details}`,
      );
      setVersion((v) => v + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = ""; // чтобы тот же файл можно было залить снова
    }
  }

  async function handleEnrich() {
    setBusy(true);
    setNotice(null);
    try {
      const result = await enrichEntities({ limit: 10 });
      const hint = result.status === "fallback" ? " (заглушка: нет OPENAI_API_KEY)" : "";
      setNotice(`Размечено записей: ${result.processed}${hint}. Потрачено $${result.cost_usd.toFixed(5)}.`);
      setVersion((v) => v + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="page-head" style={{ marginBottom: 10 }}>
        <h2 style={{ margin: 0 }}>Записи</h2>
        {showActions && (
          <div className="actions">
            <input
              ref={fileRef}
              type="file"
              accept=".csv,text/csv"
              hidden
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void handleImport(file);
              }}
            />
            <button className="ghost" disabled={busy} onClick={() => fileRef.current?.click()}>
              ⭑ Импорт CSV
            </button>
            <button disabled={busy} onClick={() => void handleEnrich()}>
              {busy ? "..." : "✦ Разметить моделью (10)"}
            </button>
            <a className="button-link" href={exportCsvUrl(filters)}>
              ↓ Выгрузить CSV
            </a>
          </div>
        )}
      </div>

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
      {notice && <div className="notice-box">{notice}</div>}

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
              <th>AI-метка</th>
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
                <td>
                  {row.ai_label ? (
                    <span className="badge ai" title={`оценка ${row.ai_score ?? "—"}`}>
                      {row.ai_label}
                      {row.ai_score !== null && <span className="muted"> · {row.ai_score}</span>}
                    </span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td className="muted mono">{row.created_at.slice(0, 16).replace("T", " ")}</td>
              </tr>
            ))}
            {!loading && rows.length === 0 && (
              <tr>
                <td colSpan={9} className="muted" style={{ padding: "18px 10px" }}>
                  Ничего не найдено. Сбрось фильтры или залей данные: `make seed` либо «Импорт CSV».
                </td>
              </tr>
            )}
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
