import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, checkFile, createReport, listDemoReports, ACCEPTED_TYPES } from "../api/client";
import { useT, type Key } from "../i18n";

export default function Home() {
  const t = useT();
  return (
    <div className="wrap home-grid">
      <section aria-labelledby="hero-title">
        <p className="eyebrow">{t("eyebrow")}</p>
        <h1 id="hero-title" className="display">{t("headline")}</h1>
        <p className="intro">{t("intro")}</p>
        <UploadCard />
      </section>
      <DemoList />
    </div>
  );
}

function UploadCard() {
  const t = useT();
  const qc = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [type, setType] = useState<"synthetic" | "real">("synthetic");
  const [file, setFile] = useState<File | null>(null);
  const [fileErr, setFileErr] = useState<Key | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [drag, setDrag] = useState(false);

  const upload = useMutation({
    mutationFn: () => createReport(file!, type),
    onSuccess: (r) => {
      qc.setQueryData(["report", r.report_id], r);
      window.location.hash = `#/report/${encodeURIComponent(r.report_id)}${type === "real" ? "?real=1" : ""}`;
    },
  });

  const pick = (f: File | undefined) => {
    if (!f) return;
    const err = checkFile(f);
    setFileErr(err ? (`err_${err}` as Key) : null);
    setFile(err ? null : f);
  };
  const valid = !!file && confirmed && !upload.isPending;

  return (
    <form className="card upload" onSubmit={(e) => { e.preventDefault(); if (valid) upload.mutate(); }}>
      <p className="label" id="type-label">{t("choose_type")}</p>
      <div className="segmented" role="radiogroup" aria-labelledby="type-label">
        {(["synthetic", "real"] as const).map((v) => (
          <button key={v} type="button" role="radio" aria-checked={type === v} onClick={() => { setType(v); setConfirmed(false); }}>
            {t(v === "synthetic" ? "type_demo" : "type_real")}
          </button>
        ))}
      </div>
      <label
        className={`dropzone${drag ? " drag" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]); }}
      >
        <input ref={inputRef} className="visually-hidden" type="file" accept={ACCEPTED_TYPES.join(",") + ",.pdf,.png,.jpg,.jpeg"} onChange={(e) => pick(e.target.files?.[0])} />
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M14 3H6v18h12V7z M14 3v4h4 M12 17v-6 m-3 3 3-3 3 3" /></svg>
        <span className="drop-main">{file ? file.name : t("drop")}</span>
        <span className="drop-hint">{t("drop_hint")}</span>
      </label>
      {fileErr && <p className="error" role="alert">{t(fileErr)}</p>}
      <label className="confirm">
        <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
        <span>{t(type === "synthetic" ? "confirm_demo" : "confirm_real")}</span>
      </label>
      <p className="fine">
        {type === "synthetic" ? <>{t("demo_note")} <a href="#/history">{t("demo_note_sign")}</a> {t("demo_note_rest")}</> : t("real_note")}
      </p>
      {upload.isError && <p className="error" role="alert">{upload.error instanceof ApiError ? upload.error.message : String(upload.error)}</p>}
      <button className="btn-primary block" type="submit" disabled={!valid} aria-busy={upload.isPending}>
        {upload.isPending ? t("working") : t("explain")} <span aria-hidden="true">→</span>
      </button>
    </form>
  );
}

function DemoList() {
  const t = useT();
  const q = useQuery({ queryKey: ["demo-reports"], queryFn: listDemoReports });
  return (
    <section aria-labelledby="demos-title" className="demos">
      <h2 id="demos-title" className="serif-h2">{t("demos_title")}</h2>
      {q.isPending && <p>{t("loading")}</p>}
      {q.isError && <p className="error" role="alert">{q.error.message}</p>}
      <ul className="demo-list">
        {q.data?.map((d) => (
          <li key={d.id} className={`card demo cat-${d.category}`}>
            <p className="mono-eyebrow">{t(`cat_${d.category}` as Key)} · {d.test_count} {t("tests")}</p>
            <h3>{d.title}</h3>
            <p className="desc">{d.description}</p>
            <div className="row">
              <a className="btn-dark small" href={`#/report/${encodeURIComponent(d.id)}`} aria-label={`${t("open")}: ${d.title}`}>{t("open")}</a>
              {d.pdf_url && <a className="btn-outline small" href={d.pdf_url} download aria-label={`${t("pdf")}: ${d.title}`}>↓ {t("pdf")}</a>}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
