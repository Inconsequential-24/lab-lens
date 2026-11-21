import { useContext, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getReport, type FlaggedTest, type ReportResult } from "../api/client";
import { consent, LangContext, useT, type Key, type Lang } from "../i18n";

export default function Results({ reportId, real }: { reportId: string; real: boolean }) {
  const t = useT();
  const q = useQuery({ queryKey: ["report", reportId], queryFn: () => getReport(reportId) });
  return (
    <div className="wrap results">
      <p><a href="#/">← {t("back")}</a></p>
      {q.isPending && <p>{t("loading")}</p>}
      {q.isError && <p className="error" role="alert">{q.error.message}</p>}
      {q.data && <ResultView r={q.data} real={real} />}
    </div>
  );
}

const testLabel = (x: FlaggedTest) => x.raw_name;
const rowId = (i: number) => `row-${i}`;

function ResultView({ r, real }: { r: ReportResult; real: boolean }) {
  const t = useT();
  const { lang } = useContext(LangContext);
  const [exLang, setExLang] = useState<Lang>(lang);
  const urgent = r.explanations.filter((e) => e.urgent_message);
  const anyCritical = r.tests.some((x) => x.is_critical) || urgent.length > 0;
  const ex = r.explanations.find((e) => e.language === exLang) ?? r.explanations[0];
  const lowConf = new Set(r.low_confidence_tests);
  const byTestId = new Map(r.tests.map((x, i) => [x.test_id, i]));
  const rec = r.recommendation;

  return (
    <>
      {anyCritical && (
        <section className="urgent" role="alert" aria-labelledby="urgent-h">
          <h2 id="urgent-h">{t("urgent_title")}</h2>
          {(["en", "hi"] as const).map((l) => {
            const msg = r.explanations.find((e) => e.language === l)?.urgent_message;
            return msg ? <p key={l} lang={l}>{msg}</p> : null;
          })}
          {urgent.length === 0 && <p>{t("not_diagnosis")}</p>}
        </section>
      )}

      <section className={`card rec urg-${rec.urgency}`} aria-labelledby="rec-h">
        <h2 id="rec-h" className="label">{t("rec_title")}</h2>
        <p className="rec-main">{t(`next_${rec.next_step}` as Key)} <span className="chip">{t(`urg_${rec.urgency}` as Key)}</span></p>
        {rec.reason_test_ids.length > 0 && (
          <p className="fine">{rec.reason_test_ids.map((id) => {
            const i = byTestId.get(id);
            return i === undefined ? id : <a key={id} href={`#${rowId(i)}`} onClick={(e) => { e.preventDefault(); document.getElementById(rowId(i))?.focus(); }}>{testLabel(r.tests[i])} </a>;
          })}</p>
        )}
        {rec.note && <p className="fine">{rec.note}</p>}
      </section>

      {r.status === "partial" && <p className="notice">{t("partial")}</p>}

      <section aria-labelledby="tests-h">
        <h1 id="tests-h" className="serif-h2">{t("results_title")}</h1>
        {r.report_date && <p className="fine">{t("report_date")}: {r.report_date}</p>}
        <div className="table-scroll" role="region" aria-labelledby="tests-h" tabIndex={0}>
          <table className="tests">
            <thead><tr>
              {(["col_test", "col_value", "col_unit", "col_range", "col_flag", "col_severity", "col_evidence"] as Key[]).map((k) => <th key={k} scope="col">{t(k)}</th>)}
            </tr></thead>
            <tbody>
              {r.tests.map((x, i) => {
                const verify = (x.test_id && lowConf.has(x.test_id)) || x.confidence < 0.8;
                return (
                  <tr key={i} id={rowId(i)} tabIndex={-1} className={x.is_critical ? "crit" : ""}>
                    <th scope="row">{testLabel(x)}{verify && <span className="verify">{t("verify")}</span>}</th>
                    <td>{x.value.comparator !== "=" ? x.value.comparator : ""}{x.value.raw || "—"}</td>
                    <td>{x.unit ?? x.unit_raw ?? "—"}</td>
                    <td>{x.ref.raw || "—"}</td>
                    <td><span className={`flag flag-${x.flag}`}>{t(`flag_${x.flag}` as Key)}</span></td>
                    <td><span className={`sev sev-${x.severity}`}>{t(`sev_${x.severity}` as Key)}</span></td>
                    <td>
                      <details>
                        <summary>{t("evidence_page")} {x.page}</summary>
                        <code>{x.source_span}</code>
                        {x.warnings && x.warnings.length > 0 && <p className="fine">{x.warnings.join(", ")}</p>}
                      </details>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {ex && (
        <section className="card" aria-labelledby="ex-h" lang={ex.language}>
          <div className="row between">
            <h2 id="ex-h" className="label">{t("explanation")}</h2>
            <div className="lang-toggle" role="group" aria-label="Explanation language">
              <button type="button" aria-pressed={exLang === "en"} onClick={() => setExLang("en")}>EN</button>
              <button type="button" aria-pressed={exLang === "hi"} onClick={() => setExLang("hi")} lang="hi">हिंदी</button>
            </div>
          </div>
          {ex.source === "template_fallback" && <p className="fine">{t("template_note")}</p>}
          <p className="summary">{ex.summary}</p>
          <ul className="statements">
            {ex.statements.map((s) => (
              <li key={s.claim_id}>{s.text}{" "}
                {s.cites.filter((c) => c.kind === "test" && byTestId.has(c.id)).map((c) => (
                  <a key={c.id} className="cite" href={`#${rowId(byTestId.get(c.id)!)}`} onClick={(e) => { e.preventDefault(); document.getElementById(rowId(byTestId.get(c.id)!))?.focus(); }}>[{c.id}]</a>
                ))}
              </li>
            ))}
          </ul>
          <p className="fine">{ex.disclaimer}</p>
        </section>
      )}

      <ListSection title={t("patterns")} items={r.patterns} />
      <ListSection title={t("warnings")} items={r.warnings} />
      <ListSection title={t("unrecognised")} items={r.unrecognised_tests} />
      {real && <SaveBox />}
    </>
  );
}

function ListSection({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return <section className="card"><h2 className="label">{title}</h2><ul>{items.map((s, i) => <li key={i}>{s}</li>)}</ul></section>;
}

function SaveBox() {
  // PLAN section 10: unticked by default; saving needs sign-in (milestone 12).
  const t = useT();
  const { lang } = useContext(LangContext);
  const [checked, setChecked] = useState(false);
  const c = consent[lang];
  return (
    <section className="card consent" lang={lang}>
      <label className="confirm">
        <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
        <span><strong>{c.title}</strong><br />{c.body}</span>
      </label>
      {checked && <p className="notice" role="status">{t("save_sign_in")}</p>}
    </section>
  );
}
