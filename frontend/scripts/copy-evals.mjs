// Copies ../evals/results_*.json into public/evals/ and writes an index.json listing them.
// Run automatically before `npm run build` (prebuild). Missing evals folder is not an error.
import { readdirSync, mkdirSync, copyFileSync, writeFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, "..", "..", "evals");
const dest = join(here, "..", "public", "evals");
mkdirSync(dest, { recursive: true });
const files = existsSync(src)
  ? readdirSync(src).filter((f) => /^results_[\w-]+\.json$/.test(f)).sort()
  : [];
for (const f of files) copyFileSync(join(src, f), join(dest, f));
writeFileSync(join(dest, "index.json"), JSON.stringify({ files }, null, 2));
console.log(`copy-evals: ${files.length} file(s) -> public/evals`);
