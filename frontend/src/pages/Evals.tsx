import { useQuery } from "@tanstack/react-query";
import { useT } from "../i18n";

// Fed from evals/results_*.json copied into public/evals/ at build time (scripts/copy-evals.mjs).
type Json = null | boolean | number | string | Json[] | { [k: string]: Json };

async function loadEvals(): Promise<{ name: string; data: Json }[]> {
  const idx = await fetch("evals/index.json");
  if (!idx.ok) return [];
  const { files } = (await idx.json()) as { files: string[] };
  return Promise.all(files.map(async (f) => ({ name: f.replace(/^results_|\.json$/g, ""), data: (await (await fetch(`evals/${f}`)).json()) as Json })));
}
const useEvals = () => useQuery({ queryKey: ["evals"], queryFn: loadEvals });

function isRate(v: Json): v is { k: number; n: number; rate: number; ci95?: Json } {
  return !!v && typeof v === "object" && !Array.isArray(v) && "rate" in v && "n" in v;
}
function fmt(v: Json): string {
  if (isRate(v)) {
    const ci = Array.isArray(v.ci95) ? ` [${(v.ci95 as number[]).map((x) => (x * 100).toFixed(1)).join("–")}]` : "";
    return `${(v.rate * 100).toFixed(1)}% (${v.k}/${v.n})${ci}`;
  }
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(4);
  if (Array.isArray(v)) return v.length > 6 ? `${v.length} items` : JSON.stringify(v);
  return String(v);
}
function flatten(v: Json, prefix = "", out: [string, string][] = [], depth = 0): [string, string][] {
  if (out.length > 400) return out;
  if (v && typeof v === "object" && !Array.isArray(v) && !isRate(v) && depth < 5) {
    for (const [k, c] of Object.entries(v)) flatten(c, prefix ? `${prefix} › ${k}` : k, out, depth + 1);
  } else out.push([prefix, fmt(v)]);
  return out;
}

function Table({ name, data }: { name: string; data: Json }) {
  const rows = flatten(data);
  return (
    <section className="card" aria-labelledby={`ev-${name}`}>
      <h2 id={`ev-${name}`} className="mono-eyebrow">{name}</h2>
      <div className="table-scroll" tabIndex={0} role="region" aria-labelledby={`ev-${name}`}>
        <table className="tests"><tbody>{rows.map(([k, v]) => <tr key={k}><th scope="row">{k}</th><td>{v}</td></tr>)}</tbody></table>
      </div>
    </section>
  );
}

export function Evaluations() {
  const t = useT();
  const q = useEvals();
  return (
    <div className="wrap narrow">
      <h1 className="display small">{t("evals_title")}</h1>
      {q.isPending && <p>{t("loading")}</p>}
      {q.isError && <p className="error" role="alert">{q.error.message}</p>}
      {q.data?.length === 0 && <p>{t("no_evals")}</p>}
      {q.data?.map((e) => <Table key={e.name} name={e.name} data={e.data} />)}
    </div>
  );
}

export function Staff() {
  // Staff view: headline numbers only (summary/overall blocks) for a quick check.
  const t = useT();
  const q = useEvals();
  const pick = (d: Json): Json => {
    if (!d || typeof d !== "object" || Array.isArray(d)) return d;
    const o = d as Record<string, Json>;
    return o.summary ?? (o.rows as Record<string, Json> | undefined)?.overall ?? o;
  };
  return (
    <div className="wrap narrow">
      <h1 className="display small">{t("staff_title")}</h1>
      {q.isPending && <p>{t("loading")}</p>}
      {q.data?.length === 0 && <p>{t("no_evals")}</p>}
      {q.data?.map((e) => <Table key={e.name} name={e.name} data={pick(e.data)} />)}
    </div>
  );
}
