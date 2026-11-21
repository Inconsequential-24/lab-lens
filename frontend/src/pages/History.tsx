import { useT } from "../i18n";

export default function History() {
  const t = useT();
  return (
    <div className="wrap narrow">
      <h1 className="display small">{t("history_title")}</h1>
      <div className="card"><p>{t("history_body")}</p></div>
    </div>
  );
}
