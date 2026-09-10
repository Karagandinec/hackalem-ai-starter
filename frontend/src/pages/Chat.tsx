import { useEffect, useRef, useState } from "react";

import { streamChat, type ChatMessage } from "../api";

type ToolNote = { role: "tool"; content: string };
type LogItem = ChatMessage | ToolNote;

const HINTS = [
  "Сколько записей за последние 7 дней?",
  "Разбей суммы по статусам",
  "Покажи 5 последних записей из Астаны",
  "Создай заявку на консультацию для Айгерим",
];

/** Панель чата с агентом. Ответ печатается по мере поступления (SSE). */
export default function Chat() {
  const [log, setLog] = useState<LogItem[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [partial, setPartial] = useState("");
  const [meta, setMeta] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [log, partial]);

  async function send(text: string) {
    const message = text.trim();
    if (!message || streaming) return;

    const history = log.filter((item): item is ChatMessage => item.role !== "tool");
    setLog((prev) => [...prev, { role: "user", content: message }]);
    setInput("");
    setStreaming(true);
    setPartial("");
    setMeta(null);
    setError(null);

    let answer = "";
    try {
      await streamChat(message, history, (event) => {
        if (event.type === "delta") {
          answer += event.text;
          setPartial(answer);
        } else if (event.type === "tool") {
          setLog((prev) => [
            ...prev,
            { role: "tool", content: `⚙ ${event.name}(${JSON.stringify(event.arguments)})` },
          ]);
        } else if (event.type === "done") {
          setMeta(event.meta);
        } else if (event.type === "error") {
          setError(event.message);
        }
      });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      if (answer) setLog((prev) => [...prev, { role: "assistant", content: answer }]);
      setPartial("");
      setStreaming(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Ассистент</h1>
          <div className="subtitle">
            Модель ходит в базу через инструменты: чтение, запись, агрегаты. Ответ печатается стримом.
          </div>
        </div>
        {log.length > 0 && (
          <button className="ghost" onClick={() => setLog([])}>
            Очистить
          </button>
        )}
      </div>

      {error && <div className="error-box">{error}</div>}

      <div className="card chat">
        <div className="chat-log" ref={logRef}>
          {log.length === 0 && !partial && (
            <div className="muted">Спроси что-нибудь про данные — модель сама сходит в базу.</div>
          )}

          {log.map((item, index) => (
            <div key={index} className={`msg ${item.role}`}>
              {item.content}
            </div>
          ))}

          {partial && <div className="msg assistant cursor">{partial}</div>}
          {streaming && !partial && <div className="msg assistant muted">думаю...</div>}
        </div>

        <form
          className="chat-form"
          onSubmit={(e) => {
            e.preventDefault();
            void send(input);
          }}
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Вопрос про данные..."
            disabled={streaming}
          />
          <button type="submit" disabled={streaming || !input.trim()}>
            {streaming ? "..." : "Отправить"}
          </button>
        </form>

        <div className="chat-hints">
          {HINTS.map((hint) => (
            <button key={hint} type="button" disabled={streaming} onClick={() => void send(hint)}>
              {hint}
            </button>
          ))}
        </div>
      </div>

      {meta && (
        <div className="muted mono" style={{ marginTop: 12 }}>
          статус: {String(meta.status)} · токенов: {String(meta.total_tokens)} · {String(meta.latency_ms)} мс ·
          ${Number(meta.cost_usd ?? 0).toFixed(5)}
          {Array.isArray(meta.tools_used) && meta.tools_used.length > 0 && ` · инструменты: ${meta.tools_used.join(", ")}`}
        </div>
      )}
    </>
  );
}
