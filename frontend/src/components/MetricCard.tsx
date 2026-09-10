import type { MetricCard as Metric } from "../api";

/**
 * Карточка метрики: значение, единица, изменение к прошлому периоду.
 *
 * Цвет изменения зависит не от знака, а от смысла метрики: у простоев и отказов
 * рост — это плохо, поэтому бэкенд помечает их lower_is_better.
 */
export default function MetricCardView({ metric }: { metric: Metric }) {
  const delta = metric.delta_pct;
  const isGood = delta === null || delta === undefined ? true : metric.lower_is_better ? delta <= 0 : delta >= 0;

  return (
    <div className="card">
      <div className="metric-label">{metric.label}</div>
      <div className="metric-value">
        {formatNumber(metric.value)}
        {metric.unit && <span className="muted" style={{ fontSize: 16 }}> {metric.unit}</span>}
      </div>
      {delta !== null && delta !== undefined ? (
        <div className={`metric-delta ${isGood ? "up" : "down"}`}>
          {delta >= 0 ? "▲" : "▼"} {Math.abs(delta)}% к прошлому периоду
        </div>
      ) : (
        <div className="metric-delta muted">нет данных за прошлый период</div>
      )}
    </div>
  );
}

export function formatNumber(value: number): string {
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)} млн`;
  if (Math.abs(value) >= 10_000) return `${(value / 1_000).toFixed(0)} тыс`;
  return value.toLocaleString("ru-RU", { maximumFractionDigits: 1 });
}
