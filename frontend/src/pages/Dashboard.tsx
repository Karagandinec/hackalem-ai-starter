import { useEffect, useState } from "react";

import { getDashboard, type DashboardSummary } from "../api";
import Chart from "../components/Chart";
import DataTable from "../components/DataTable";
import MetricCardView from "../components/MetricCard";

/** Шаблон дашборда: 4 карточки + график + таблица. Переделывай под свой кейс. */
export default function Dashboard() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [metric, setMetric] = useState<"count" | "amount">("count");

  useEffect(() => {
    getDashboard(days)
      .then((result) => {
        setData(result);
        setError(null);
      })
      .catch((err: Error) => setError(err.message));
  }, [days]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Дашборд</h1>
          <div className="subtitle">Сводка за последние {days} дней</div>
        </div>
        <div className="field">
          <label htmlFor="period">Период</label>
          <select id="period" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={7}>7 дней</option>
            <option value={30}>30 дней</option>
            <option value={90}>90 дней</option>
          </select>
        </div>
      </div>

      {error && (
        <div className="error-box">
          Бэкенд не отвечает: {error}. Проверь, что запущен `make dev`, и что база залита `make seed`.
        </div>
      )}

      <div className="cards-grid">
        {(data?.cards ?? []).map((card) => (
          <MetricCardView key={card.key} metric={card} />
        ))}
        {!data && !error && <div className="card muted">Загружаю метрики...</div>}
      </div>

      <div className="grid-2">
        <div className="card">
          <div className="page-head" style={{ marginBottom: 8 }}>
            <h2 style={{ margin: 0 }}>Динамика</h2>
            <div>
              <button className="ghost" onClick={() => setMetric(metric === "count" ? "amount" : "count")}>
                {metric === "count" ? "показать сумму" : "показать количество"}
              </button>
            </div>
          </div>
          <Chart
            data={data?.timeseries ?? []}
            dataKey={metric}
            label={metric === "count" ? "Записей" : "Сумма"}
          />
        </div>

        <DataTable defaultDays={days} limit={25} />
      </div>
    </>
  );
}
