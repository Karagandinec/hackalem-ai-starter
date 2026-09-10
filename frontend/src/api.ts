/**
 * Единственное место, где фронт общается с бэкендом.
 * В dev-режиме путь /api проксируется на FastAPI (см. vite.config.ts),
 * поэтому URL бэкенда в коде не зашит.
 */

const BASE = "/api";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem("token");
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText} — ${path}`);
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

// --- Типы ответов бэкенда (держи в согласии с backend/app/schemas.py) ---

export type Health = {
  status: string;
  app?: string;
  entities?: number;
  ai_enabled?: boolean;
  model?: string;
};

export type MetricCard = {
  key: string;
  label: string;
  value: number;
  unit: string;
  delta_pct: number | null;
};

export type TimeseriesPoint = { date: string; count: number; amount: number };

export type DashboardSummary = { cards: MetricCard[]; timeseries: TimeseriesPoint[] };

export type Entity = {
  id: number;
  name: string;
  type: string;
  status: string;
  category: string | null;
  city: string | null;
  amount: number;
  description: string | null;
  ai_label: string | null;
  ai_score: number | null;
  owner_id: number | null;
  created_at: string;
};

export type ImportResult = {
  imported: number;
  skipped: number;
  errors: string[];
  columns_used: string[];
};

export type EnrichResult = {
  processed: number;
  status: string;
  cost_usd: number;
  rows: { id: number; name: string; ai_label: string | null; ai_score: number | null; reason: string }[];
};

export type AiCall = {
  id: number;
  created_at: string;
  purpose: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  latency_ms: number;
  cost_usd: number;
  cached: boolean;
  status: string;
};

export type AiMetrics = {
  total_calls: number;
  ok_calls: number;
  error_calls: number;
  fallback_calls: number;
  cached_calls: number;
  cache_hit_rate: number;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_cost_usd: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  by_purpose: { purpose: string; calls: number; tokens: number; cost_usd: number; avg_latency_ms: number }[];
  recent: AiCall[];
};

export const getHealth = () => api<Health>("/health");
export const getDashboard = (days = 30) => api<DashboardSummary>(`/dashboard?days=${days}`);
export const getAiMetrics = () => api<AiMetrics>("/ai/metrics");

export type EntityFilters = {
  date_from?: string;
  date_to?: string;
  status?: string;
  search?: string;
  limit?: number;
};

function toQuery(params: EntityFilters): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") query.set(key, String(value));
  });
  return query.toString();
}

export const getEntities = (params: EntityFilters) => api<Entity[]>(`/entities?${toQuery(params)}`);

/** Ссылка на выгрузку — обычный <a href>, файл скачивает браузер. */
export const exportCsvUrl = (params: EntityFilters) => `${BASE}/entities/export.csv?${toQuery(params)}`;

/** Загрузка CSV. Content-Type тут не ставим: браузер сам проставит boundary. */
export async function importEntities(file: File): Promise<ImportResult> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${BASE}/entities/import`, { method: "POST", body: form });
  if (!response.ok) throw new Error(`Импорт не удался: ${response.status} ${response.statusText}`);
  return (await response.json()) as ImportResult;
}

/** Разметка записей моделью: результат пишется в ai_label / ai_score в базе. */
export const enrichEntities = (body: { entity_ids?: number[]; instruction?: string; limit?: number }) =>
  api<EnrichResult>("/ai/enrich", { method: "POST", body: JSON.stringify(body) });

// --- Чат со стримингом ------------------------------------------------------

export type ChatEvent =
  | { type: "delta"; text: string }
  | { type: "tool"; round: number; name: string; arguments: Record<string, unknown>; result: unknown }
  | { type: "done"; meta: Record<string, unknown> }
  | { type: "error"; message: string };

export type ChatMessage = { role: "user" | "assistant"; content: string };

/**
 * Читает Server-Sent Events от POST /api/ai/chat и отдаёт события по мере
 * поступления. Обычный EventSource тут не подходит: он умеет только GET.
 */
export async function streamChat(
  message: string,
  history: ChatMessage[],
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${BASE}/ai/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, history }),
    signal,
  });
  if (!response.body) throw new Error("Бэкенд не отдал поток");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // События разделены пустой строкой: "data: {...}\n\n"
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data:")) continue;
      const payload = line.slice(5).trim();
      if (payload === "[DONE]") return;
      try {
        onEvent(JSON.parse(payload) as ChatEvent);
      } catch {
        // Битый кусок JSON игнорируем — поток важнее одного события.
      }
    }
  }
}
