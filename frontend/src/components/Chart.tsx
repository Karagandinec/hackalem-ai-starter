import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { TimeseriesPoint } from "../api";

/**
 * График динамики. Меняешь метрику — меняешь dataKey ("count" или "amount").
 * Другой тип графика — замени AreaChart на LineChart/BarChart из recharts.
 */
export default function Chart({
  data,
  dataKey = "count",
  label = "Записей в день",
}: {
  data: TimeseriesPoint[];
  dataKey?: "count" | "amount";
  label?: string;
}) {
  if (data.length === 0) {
    return <div className="muted">Данных за период нет. Запусти `make seed`.</div>;
  }

  return (
    <ResponsiveContainer width="100%" height={260}>
      <AreaChart data={data} margin={{ top: 6, right: 8, left: -18, bottom: 0 }}>
        <defs>
          <linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#4f8cff" stopOpacity={0.45} />
            <stop offset="100%" stopColor="#4f8cff" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#262e3a" vertical={false} />
        <XAxis
          dataKey="date"
          tick={{ fill: "#8b949e", fontSize: 11 }}
          tickLine={false}
          axisLine={{ stroke: "#262e3a" }}
          tickFormatter={(value: string) => value.slice(5)}
          minTickGap={24}
        />
        <YAxis tick={{ fill: "#8b949e", fontSize: 11 }} tickLine={false} axisLine={false} width={56} />
        <Tooltip
          contentStyle={{
            background: "#161b22",
            border: "1px solid #262e3a",
            borderRadius: 10,
            color: "#e6edf3",
            fontSize: 12,
          }}
          labelStyle={{ color: "#8b949e" }}
          formatter={(value) => [Number(value ?? 0).toLocaleString("ru-RU"), label]}
        />
        <Area type="monotone" dataKey={dataKey} stroke="#4f8cff" strokeWidth={2} fill="url(#fill)" />
      </AreaChart>
    </ResponsiveContainer>
  );
}
