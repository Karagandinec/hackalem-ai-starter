import { useEffect, useRef, useState } from "react";

import { enrichAssets, exportCsvUrl, getAssets, importAssets, type Asset, type AssetFilters } from "../api";
import { formatNumber } from "./MetricCard";

const STATUSES = ["в работе", "ТО", "в ремонте", "простой", "резерв"];
const TYPES = ["самосвал", "экскаватор", "буровой станок", "бульдозер", "конвейер", "насосная установка"];

/** CSS-класс бейджа статуса: латиница, потому что в классах кириллица неудобна. */
const STATUS_CLASS: Record<string, string> = {
  "в работе": "ok",
  ТО: "warn",
  "в ремонте": "warn",
  простой: "bad",
  резерв: "muted-badge",
};
const RISK_CLASS: Record<string, string> = {
  низкий: "ok",
  средний: "warn",
  высокий: "bad",
  критический: "bad",
};

/**
 * Таблица техники с фильтрами: период, статус, тип, поиск по бортовому номеру.
 * Фильтрует бэкенд (GET /api/assets), фронт только собирает параметры —
 * так таблица не ломается на больших парках.
 *
 * showActions=true добавляет панель «импорт CSV / оценить риск / выгрузка».
 * На дашборде она не нужна, на странице техники — нужна.
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
  const [dateFrom, setDateFrom] = useState(daysAgo(defaultDays * 6));
  const [dateTo, setDateTo] = useState(daysAgo(0));
  const [status, setStatus] = useState("");
  const [type, setType] = useState("");
  const [search, setSearch] = useState("");
  const [rows, setRows] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState(0); // счётчик перезагрузок после действий
  const fileRef = useRef<HTMLInputElement>(null);

  const filters: AssetFilters = { date_from: dateFrom, date_to: dateTo, status, type, search, limit };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getAssets({ date_from: dateFrom, date_to: dateTo, status, type, search, limit })
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
  }, [dateFrom, dateTo, status, type, search, limit, version]);

  async function handleImport(file: File) {
    setBusy(true);
    setNotice(null);
    try {
      const result = await importAssets(file);
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
      const result = await enrichAssets({ limit: 10 });
      const hint = result.status === "fallback" ? " (заглушка: нет OPENAI_API_KEY)" : "";
      setNotice(
        `Оценено единиц: ${result.processed}${hint}. Потрачено $${result.cost_usd.toFixed(5)}. ` +
          (result.rows[0]?.reason ? `Пример: ${result.rows[0].name} — ${result.rows[0].reason}` : ""),
      );
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
        <h2 style={{ margin: 0 }}>Техника</h2>
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
              {busy ? "..." : "✦ Оценить риск отказа (10)"}
            </button>
            <a className="button-link" href={exportCsvUrl(filters)}>
              ↓ Выгрузить CSV
            </a>
          </div>
        )}
      </div>

      <div className="filters">
        <div className="field">
          <label htmlFor="date-from">В парке с</label>
          <input id="date-from" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="date-to">по</label>
          <input id="date-to" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="status">Статус</label>
          <select id="status" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">все</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="type">Тип</label>
          <select id="type" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">все</option>
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="search">Поиск</label>
          <input
            id="search"
            placeholder="борт. номер"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <button
          className="ghost"
          onClick={() => {
            setDateFrom(daysAgo(defaultDays * 6));
            setDateTo(daysAgo(0));
            setStatus("");
            setType("");
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
              <th>Техника</th>
              <th>Тип</th>
              <th>Статус</th>
              <th>Участок</th>
              <th className="num">Наработка, мч</th>
              <th className="num">Смена, т</th>
              <th>Риск отказа</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td className="muted mono">{row.id}</td>
                <td>{row.name}</td>
                <td className="muted">{row.type}</td>
                <td>
                  <span className={`badge ${STATUS_CLASS[row.status] ?? "muted-badge"}`}>{row.status}</span>
                </td>
                <td className="muted">{row.site ?? "—"}</td>
                <td className="num">{formatNumber(row.engine_hours)}</td>
                <td className="num">{row.output_tonnes ? formatNumber(row.output_tonnes) : "—"}</td>
                <td>
                  {row.ai_label ? (
                    <span className={`badge ${RISK_CLASS[row.ai_label] ?? "ai"}`}>
                      {row.ai_label}
                      {row.ai_score !== null && <span className="muted"> · {row.ai_score}</span>}
                    </span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
              </tr>
            ))}
            {!loading && rows.length === 0 && (
              <tr>
                <td colSpan={8} className="muted" style={{ padding: "18px 10px" }}>
                  Ничего не найдено. Сбрось фильтры или залей парк: `make seed` либо «Импорт CSV».
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="muted" style={{ marginTop: 12, fontSize: 12 }}>
        {loading ? "Загружаю..." : `Показано ${rows.length} единиц (лимит ${limit}), сверху самая изношенная`}
      </div>
    </div>
  );
}

function daysAgo(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
}
