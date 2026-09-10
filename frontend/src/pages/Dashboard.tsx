import { useEffect, useState } from "react";

import { getDashboard, type DashboardSummary } from "../api";
import Chart from "../components/Chart";
import DataTable from "../components/DataTable";
import MetricCardView from "../components/MetricCard";

/** Дашборд диспетчера: готовность парка, простои, отказы, выработка. */
export default function Dashboard() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [metric, setMetric] = useState<"downtime_hours" | "events">("downtime_hours");

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
          <h1>Диспетчерская</h1>
          <div className="subtitle">Состояние парка и простои за последние {days} дней</div>
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
            <h2 style={{ margin: 0 }}>
              {metric === "downtime_hours" ? "Простои по дням, часов" : "Событий по дням"}
            </h2>
            <div>
              <button
                className="ghost"
                onClick={() => setMetric(metric === "downtime_hours" ? "events" : "downtime_hours")}
              >
                {metric === "downtime_hours" ? "показать количество событий" : "показать часы простоя"}
              </button>
            </div>
          </div>
          <Chart
            data={data?.timeseries ?? []}
            dataKey={metric}
            label={metric === "downtime_hours" ? "Часов простоя" : "Событий"}
          />
        </div>

        <DataTable defaultDays={days} limit={25} />
      </div>
    </>
  );
}
