import { useEffect, useState } from "react";

import { getAiMetrics, type AiMetrics as Metrics } from "../api";

/** Сводка по таблице ai_calls: сколько вызовов, токенов, денег и как быстро. */
export default function AiMetrics() {
  const [data, setData] = useState<Metrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () =>
      getAiMetrics()
        .then((result) => {
          setData(result);
          setError(null);
        })
        .catch((err: Error) => setError(err.message));
    void load();
    const timer = setInterval(load, 5000); // обновляем на ходу, удобно во время демо
    return () => clearInterval(timer);
  }, []);

  if (error) return <div className="error-box">Не удалось получить метрики: {error}</div>;
  if (!data) return <div className="muted">Загружаю...</div>;

  const cards = [
    { label: "Вызовов", value: data.total_calls.toString() },
    { label: "Токенов", value: data.total_tokens.toLocaleString("ru-RU") },
    { label: "Потрачено", value: `$${data.total_cost_usd.toFixed(4)}` },
    { label: "Медленный хвост p95", value: `${data.p95_latency_ms} мс` },
  ];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>AI-метрики</h1>
          <div className="subtitle">
            Каждый вызов модели пишется в таблицу ai_calls. Обновляется автоматически каждые 5 секунд.
          </div>
        </div>
      </div>

      <div className="cards-grid">
        {cards.map((card) => (
          <div className="card" key={card.label}>
            <div className="metric-label">{card.label}</div>
            <div className="metric-value">{card.value}</div>
          </div>
        ))}
      </div>

      <div className="card" style={{ marginBottom: 14 }}>
        <h2>Статусы</h2>
        <div className="muted" style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
          <span>
            <span className="dot ok" />
            успешных: {data.ok_calls}
          </span>
          <span>
            <span className="dot off" />
            заглушек: {data.fallback_calls}
          </span>
          <span>
            <span className="dot err" />
            ошибок: {data.error_calls}
          </span>
          <span>из кэша: {data.cached_calls} ({data.cache_hit_rate}%)</span>
          <span>средняя латентность: {data.avg_latency_ms} мс</span>
          <span>
            токены: {data.prompt_tokens} вход / {data.completion_tokens} выход
          </span>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 14 }}>
        <h2>По назначению вызова</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>purpose</th>
                <th className="num">вызовов</th>
                <th className="num">токенов</th>
                <th className="num">стоимость</th>
                <th className="num">средняя латентность</th>
              </tr>
            </thead>
            <tbody>
              {data.by_purpose.map((row) => (
                <tr key={row.purpose}>
                  <td className="mono">{row.purpose}</td>
                  <td className="num">{row.calls}</td>
                  <td className="num">{row.tokens.toLocaleString("ru-RU")}</td>
                  <td className="num">${row.cost_usd.toFixed(5)}</td>
                  <td className="num">{row.avg_latency_ms} мс</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h2>Последние вызовы</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Время</th>
                <th>purpose</th>
                <th>модель</th>
                <th>статус</th>
                <th className="num">токены</th>
                <th className="num">мс</th>
                <th className="num">$</th>
              </tr>
            </thead>
            <tbody>
              {data.recent.map((call) => (
                <tr key={call.id}>
                  <td className="muted mono">{call.id}</td>
                  <td className="muted mono">{call.created_at.slice(11, 19)}</td>
                  <td className="mono">{call.purpose}</td>
                  <td className="muted mono">{call.model}</td>
                  <td>
                    <span className={`badge ${call.status === "ok" ? "ok" : "warn"}`}>
                      {call.cached ? "cached" : call.status}
                    </span>
                  </td>
                  <td className="num">{call.total_tokens}</td>
                  <td className="num">{call.latency_ms}</td>
                  <td className="num">{call.cost_usd.toFixed(5)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="muted" style={{ marginTop: 12, fontSize: 12 }}>
          Полный промпт и ответ конкретного вызова: GET /api/ai/calls/&lt;id&gt;
        </div>
      </div>
    </>
  );
}
