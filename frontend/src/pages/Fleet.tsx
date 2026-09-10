import DataTable from "../components/DataTable";

/** Полный список техники. Отдельная страница, чтобы дашборд не разрастался. */
export default function Fleet() {
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Парк техники</h1>
          <div className="subtitle">
            Залей свой парк из CSV, оцени риск отказа моделью, выгрузи результат.
          </div>
        </div>
      </div>
      <DataTable defaultDays={60} limit={200} showActions />
    </>
  );
}
