// Opt-in save under the result (PLAN section 10): unticked consent, required report date,
// 409 already_saved notice, 409 overlap -> per-test choice, resend with overlap_choice.
import { useContext, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, NOTICE_VERSION, saveReport, type ConflictError, type OverlapItem, type ReportResult } from "../api/client";
import { canSignIn, GOOGLE_CLIENT_ID, signIn, useSignedIn } from "../auth";
import { consent, LangContext, useT, type Key } from "../i18n";

type Choice = "keep_new" | "keep_existing" | "keep_both";
const MIN_DATE = "1990-01-01";
const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
export function dateError(v: string): Key | null {
  if (!v) return "s_date_req";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(v) || Number.isNaN(Date.parse(v))) return "s_date_req";
  if (v > today()) return "s_date_future";
  if (v < MIN_DATE) return "s_date_old";
  return null;
}

export default function SaveBox({ r }: { r: ReportResult }) {
  const t = useT();
  const { lang } = useContext(LangContext);
  const signedIn = useSignedIn();
  const qc = useQueryClient();
  const [checked, setChecked] = useState(false);
  const [date, setDate] = useState(r.report_date ?? "");
  const [touched, setTouched] = useState(false);
  const [overlaps, setOverlaps] = useState<OverlapItem[]>([]);
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const c = consent[lang];
  const dErr = dateError(date);

  const save = useMutation({
    mutationFn: (overlap_choice?: Record<string, Choice>) =>
      saveReport(r.report_id, { consent: true, notice_version: NOTICE_VERSION, report_date: date, ...(overlap_choice ? { overlap_choice } : {}) }),
    onSuccess: () => { setOverlaps([]); qc.invalidateQueries({ queryKey: ["history"] }); },
    onError: (e) => {
      if (e instanceof ApiError && e.reason === "overlap") {
        const items = (e.body as ConflictError | undefined)?.overlaps ?? [];
        setOverlaps(items);
        setChoices(Object.fromEntries(items.map((o) => [o.test_id, "keep_both" as Choice])));
      }
    },
  });
  const err = save.error instanceof ApiError ? save.error : null;
  const already = err?.reason === "already_saved";
  const savedOn = already ? (err.body as ConflictError | undefined)?.saved_on : undefined;

  return (
    <section className="card consent" lang={lang} aria-labelledby="save-h">
      <h2 id="save-h" className="visually-hidden">{c.title}</h2>
      <label className="confirm">
        <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
        <span><strong>{c.title}</strong><br />{c.body}</span>
      </label>
      {checked && !signedIn && (
        <div className="notice" role="status">
          <p>{t("s_need_sign_in")}</p>
          {canSignIn
            ? <button type="button" className="btn-outline small" onClick={signIn}>{t("google_sign_in")}</button>
            : <><button type="button" className="btn-outline small" disabled>{t("google_sign_in")}</button> {!GOOGLE_CLIENT_ID && <span className="fine">{t("google_unavailable")}</span>}</>}
        </div>
      )}
      {checked && signedIn && !save.isSuccess && (
        <form className="save-form" noValidate onSubmit={(e) => { e.preventDefault(); setTouched(true); if (!dErr) save.mutate(undefined); }}>
          <label htmlFor="save-date" className="label">{t("s_date")}</label>
          <p className="fine" id="save-date-hint">{t("s_date_hint")}</p>
          <input id="save-date" type="date" required min={MIN_DATE} max={today()} value={date}
            aria-invalid={touched && !!dErr} aria-describedby={`save-date-hint${touched && dErr ? " save-date-err" : ""}`}
            onChange={(e) => { setDate(e.target.value); setOverlaps([]); save.reset(); }} />
          {touched && dErr && <p id="save-date-err" className="error" role="alert">{t(dErr)}</p>}

          {overlaps.length > 0 ? (
            <fieldset className="overlaps">
              <legend>{t("s_overlap")}</legend>
              {overlaps.map((o) => (
                <div key={o.test_id} className="overlap-row" role="radiogroup" aria-label={o.new.raw_name}>
                  <p><strong>{o.new.raw_name}</strong> · {o.report_date}<br />
                    <span className="fine">{t("s_existing")}: {o.existing.value.raw} {o.existing.unit ?? ""} · {t("s_new")}: {o.new.value.raw} {o.new.unit ?? ""}</span></p>
                  {(["keep_new", "keep_existing", "keep_both"] as Choice[]).map((ch) => (
                    <label key={ch} className="radio">
                      <input type="radio" name={`ov-${o.test_id}`} checked={choices[o.test_id] === ch}
                        onChange={() => setChoices({ ...choices, [o.test_id]: ch })} /> {t(`s_${ch}` as Key)}
                    </label>
                  ))}
                </div>
              ))}
              <button type="button" className="btn-primary" disabled={save.isPending} onClick={() => save.mutate(choices)}>{t("s_resend")}</button>
            </fieldset>
          ) : (
            <button type="submit" className="btn-primary" disabled={save.isPending || already}>{save.isPending ? t("s_saving") : t("s_save")}</button>
          )}
          {already && <p className="notice" role="status">{t("s_already")}{savedOn ? ` (${savedOn})` : ""}. <a href="#/history">{t("nav_history")}</a></p>}
          {err && !already && err.reason !== "overlap" && <p className="error" role="alert">{err.message}</p>}
        </form>
      )}
      {save.isSuccess && <p className="notice" role="status">{t("s_saved")} <a href="#/history">{t("nav_history")}</a></p>}
    </section>
  );
}
