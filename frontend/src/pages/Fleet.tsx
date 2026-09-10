import DataTable from "../components/DataTable";

/** Полный список записей. Отдельная страница, чтобы дашборд не разрастался. */
export default function Entities() {
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Данные</h1>
          <div className="subtitle">
            Таблица entities с фильтрами. Залей свой CSV, размечай записи моделью, выгружай результат.
          </div>
        </div>
      </div>
      <DataTable defaultDays={60} limit={200} showActions />
    </>
  );
}
