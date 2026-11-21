import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { deleteAllHistory, deleteHistoryItem, getTrend, listHistory, type SavedReport, type TrendPoint } from "../api/client";
import { canSignIn, GOOGLE_CLIENT_ID, signIn, signOut, useSignedIn } from "../auth";
import { useT, type Key } from "../i18n";

export default function History() {
  const t = useT();
  const signedIn = useSignedIn();
  return (
    <div className="wrap narrow">
      <h1 className="display small">{t("history_title")}</h1>
      {signedIn ? <SignedIn /> : (
        <div className="card">
          <p>{t("h_signed_out")}</p>
          {canSignIn
            ? <button type="button" className="btn-primary" onClick={signIn}>{t("google_sign_in")}</button>
            : <><button type="button" className="btn-primary" disabled aria-describedby="g-note">{t("google_sign_in")}</button>
                {!GOOGLE_CLIENT_ID && <p id="g-note" className="fine">{t("google_unavailable")}</p>}</>}
        </div>
      )}
    </div>
  );
}

type Pending = { kind: "one"; id: string; date: string } | { kind: "all" } | null;

function SignedIn() {
  const t = useT();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["history"], queryFn: listHistory });
  const [pending, setPending] = useState<Pending>(null);
  const [done, setDone] = useState(false);
  const del = useMutation({
    mutationFn: (p: NonNullable<Pending>) => (p.kind === "all" ? deleteAllHistory() : deleteHistoryItem(p.id)),
    onSuccess: () => { setPending(null); setDone(true); qc.invalidateQueries({ queryKey: ["history"] }); qc.invalidateQueries({ queryKey: ["trend"] }); },
  });
  const reports = q.data ?? [];
  const confirmText = pending?.kind === "one" ? t("h_confirm_one").replace("{d}", pending.date) : t("h_confirm_all");
  const confirmBox = (
    <div className="notice confirm-box" role="alertdialog" aria-labelledby="del-q">
      <p id="del-q">{confirmText}</p>
      <div className="row">
        <button type="button" className="btn-dark small" disabled={del.isPending} onClick={() => pending && del.mutate(pending)} autoFocus>{t("h_yes")}</button>
        <button type="button" className="btn-outline small" onClick={() => setPending(null)}>{t("h_cancel")}</button>
      </div>
      {del.isError && <p className="error" role="alert">{del.error.message}</p>}
    </div>
  );

  return (
    <>
      <div className="row between"><p className="fine">{t("h_signed_out").split(".")[0]}.</p>
        <button type="button" className="btn-outline small" onClick={signOut}>{t("sign_out")}</button></div>
      {done && <p className="fine" role="status">{t("h_deleted")}</p>}
      {q.isPending && <p>{t("loading")}</p>}
      {q.isError && <p className="error" role="alert">{q.error.message}</p>}
      {q.data && reports.length === 0 && <div className="card"><p>{t("h_empty")}</p></div>}
      {reports.length > 0 && <Trends reports={reports} />}
      {reports.length > 0 && (
        <section aria-labelledby="saved-h">
          <h2 id="saved-h" className="serif-h2">{t("h_saved")}</h2>
          <ul className="saved-list">
            {reports.map((s) => (
              <li key={s.saved_report_id} className="card">
                <div className="row between">
                  <div><strong>{s.report_date}</strong> <span className="fine">· {s.tests.length} {t("h_tests")}</span>
                    <p className="fine saved-tests">{s.tests.map((x) => x.raw_name).join(", ")}</p></div>
                  <button type="button" className="btn-outline small" onClick={() => setPending({ kind: "one", id: s.saved_report_id, date: s.report_date })}>{t("h_delete")}</button>
                </div>
                {pending?.kind === "one" && pending.id === s.saved_report_id && confirmBox}
              </li>
            ))}
          </ul>
          <button type="button" className="btn-outline" onClick={() => setPending({ kind: "all" })}>{t("h_delete_all")}</button>
          {pending?.kind === "all" && confirmBox}
        </section>
      )}
    </>
  );
}

function Trends({ reports }: { reports: SavedReport[] }) {
  const t = useT();
  const tests = new Map<string, string>();
  reports.forEach((s) => s.tests.forEach((x) => x.test_id && !tests.has(x.test_id) && tests.set(x.test_id, x.raw_name)));
  const ids = [...tests.keys()];
  const [sel, setSel] = useState(ids[0]);
  const testId = ids.includes(sel) ? sel : ids[0];
  const q = useQuery({ queryKey: ["trend", testId], queryFn: () => getTrend(testId), enabled: !!testId });
  return (
    <section className="card" aria-labelledby="trend-h">
      <div className="row between">
        <h2 id="trend-h" className="label">{t("h_trends")}</h2>
        <label className="row fine">{t("h_pick")}
          <select value={testId} onChange={(e) => setSel(e.target.value)}>
            {ids.map((id) => <option key={id} value={id}>{tests.get(id)}</option>)}
          </select>
        </label>
      </div>
      {q.data && <TrendChart points={q.data.points} name={tests.get(testId) ?? testId} />}
      <p className="fine">{t("h_trend_note")}</p>
    </section>
  );
}

// Inline SVG: line through same-unit points, each with its own range band; different-unit
// points sit on a separate strip and are never joined or scaled with the others.
function TrendChart({ points, name }: { points: TrendPoint[]; name: string }) {
  const t = useT();
  const main = points.filter((p) => !p.different_unit && p.value.number !== null);
  const other = points.filter((p) => p.different_unit || p.value.number === null);
  if (!points.length) return null;
  const W = 640, H = 240, L = 48, R = 48, T = 16, B = 72, stripY = H - B + 26;
  const vals = main.flatMap((p) => [p.value.number!, p.ref.low, p.ref.high].filter((v): v is number => v !== null));
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (!vals.length) { lo = 0; hi = 1; }
  const pad = (hi - lo || 1) * 0.12; lo -= pad; hi += pad;
  const n = points.length;
  const x = (i: number) => L + (n === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (n - 1));
  const y = (v: number) => T + ((hi - v) / (hi - lo)) * (H - T - B);
  const idx = (p: TrendPoint) => points.indexOf(p);
  const bw = Math.max(10, Math.min(36, (W - L - R) / Math.max(n, 2) / 2));
  const ticks = [lo + pad, (lo + hi) / 2, hi - pad];
  const label = (p: TrendPoint) => `${p.report_date}: ${p.value.raw} ${p.unit ?? ""}${p.ref.raw ? ` (range ${p.ref.raw})` : ""}${p.is_critical ? `, ${t("h_critical")}` : ""}${p.different_unit ? `, ${t("h_diff_unit")}` : ""}`;
  return (
    <figure className="trend">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby="trend-title trend-desc" preserveAspectRatio="xMidYMid meet">
        <title id="trend-title">{name}</title>
        <desc id="trend-desc">{points.map(label).join("; ")}</desc>
        {ticks.map((v, i) => (
          <g key={i}><line x1={L} x2={W - R} y1={y(v)} y2={y(v)} className="grid" />
            <text x={L - 6} y={y(v) + 4} textAnchor="end" className="axis">{+v.toPrecision(3)}</text></g>
        ))}
        {main.map((p) => (p.ref.low !== null || p.ref.high !== null) && (
          <rect key={`b${idx(p)}`} className="band" x={x(idx(p)) - bw / 2} width={bw}
            y={y(Math.min(p.ref.high ?? hi, hi))} height={Math.max(0, y(Math.max(p.ref.low ?? lo, lo)) - y(Math.min(p.ref.high ?? hi, hi)))} />
        ))}
        {main.length > 1 && <polyline className="line" points={main.map((p) => `${x(idx(p))},${y(p.value.number!)}`).join(" ")} />}
        {main.map((p) => (
          <g key={`p${idx(p)}`}>
            {p.is_critical
              ? <rect className="pt crit" x={x(idx(p)) - 6} y={y(p.value.number!) - 6} width={12} height={12} transform={`rotate(45 ${x(idx(p))} ${y(p.value.number!)})`} />
              : <circle className="pt" cx={x(idx(p))} cy={y(p.value.number!)} r={5} />}
            <title>{label(p)}</title>
          </g>
        ))}
        {other.length > 0 && <line x1={L} x2={W - R} y1={stripY} y2={stripY} className="grid dashed" />}
        {other.map((p) => (
          <g key={`o${idx(p)}`}>
            <circle className="pt diff" cx={x(idx(p))} cy={stripY} r={5} />
            <text x={x(idx(p)) + 9} y={stripY + 4} className="axis">{p.value.raw} {p.unit ?? ""}</text>
            <title>{label(p)}</title>
          </g>
        ))}
        {points.map((p, i) => <text key={`d${i}`} x={x(i)} y={H - 6} textAnchor="middle" className="axis">{p.report_date}</text>)}
      </svg>
      <figcaption className="legend fine">
        <span><svg width="14" height="14" aria-hidden="true"><rect className="band" width="14" height="14" /></svg> {t("col_range" as Key)}</span>
        <span><svg width="14" height="14" aria-hidden="true"><rect className="pt crit" x="3" y="3" width="8" height="8" transform="rotate(45 7 7)" /></svg> {t("h_critical")}</span>
        {other.length > 0 && <span><svg width="14" height="14" aria-hidden="true"><circle className="pt diff" cx="7" cy="7" r="5" /></svg> {t("h_diff_unit")}</span>}
      </figcaption>
    </figure>
  );
}
