// Fixtures for VITE_MOCK=1. Typed against the generated schema so they stay contract-shaped.
import type { components } from "./schema";
import { ApiError } from "./errors";
type ReportResult = components["schemas"]["ReportResult"];
type FlaggedTest = components["schemas"]["FlaggedTest"];
type DemoReport = import("./client").DemoReport;

export function delay<T>(value: T, ms = 300): Promise<T> {
  return new Promise((r) => setTimeout(() => r(value), ms));
}

function t(p: Partial<FlaggedTest> & Pick<FlaggedTest, "raw_name" | "test_id" | "panel">, num: number | null, unit: string | null, low: number | null, high: number | null): FlaggedTest {
  const raw = num === null ? "" : String(num);
  const refRaw = low !== null && high !== null ? `${low} - ${high}` : "";
  return {
    value: { raw, number: num, comparator: "=" },
    unit_raw: unit, unit, ref: { raw: refRaw, low, high, source: refRaw ? "report" : "none" },
    printed_flag: null, remark: null, page: 1,
    source_span: `${p.raw_name} ${raw} ${unit ?? ""} ${refRaw}`.trim(),
    confidence: 0.97, flag: "normal", severity: "normal", is_critical: false,
    flag_disagrees_with_printed: false, warnings: [], ...p,
  };
}

const metrics = { latency_ms: { total: 5400 }, tokens_in: 7700, tokens_out: 2100, tokens_cached: 0, cost_inr: 0.45, retries: 0, model_versions: {} };
const disclaimerEn = "This explains your report. It is not medical advice or a diagnosis.";
const disclaimerHi = "यह आपकी रिपोर्ट को समझाता है। यह चिकित्सा सलाह या निदान नहीं है।";

const normal: ReportResult = {
  report_id: "demo_normal", status: "complete", report_date: "2026-11-02", panels: ["cbc"],
  tests: [
    t({ raw_name: "HGB", test_id: "hemoglobin", panel: "cbc" }, 13.4, "g/dL", 12, 15),
    t({ raw_name: "WBC", test_id: "wbc", panel: "cbc" }, 7.1, "10^3/uL", 4, 11),
    t({ raw_name: "PLT", test_id: "platelets", panel: "cbc" }, 250, "10^3/uL", 150, 410),
  ],
  unrecognised_tests: [], lab_remarks: [], patterns: [],
  explanations: [
    { language: "en", source: "llm", urgent_message: null, summary: "All of your results are within the ranges printed on the report.",
      statements: [{ claim_id: "c1", text: "Your hemoglobin is 13.4 g/dL, within the usual range of 12.0 to 15.0 g/dL.", cites: [{ kind: "test", id: "hemoglobin" }] }], disclaimer: disclaimerEn },
    { language: "hi", source: "llm", urgent_message: null, summary: "आपके सभी परिणाम रिपोर्ट पर छपी सीमा के भीतर हैं।",
      statements: [{ claim_id: "c1", text: "आपका हीमोग्लोबिन 13.4 g/dL है, जो 12.0 से 15.0 g/dL की सामान्य सीमा के भीतर है।", cites: [{ kind: "test", id: "hemoglobin" }] }], disclaimer: disclaimerHi },
  ],
  recommendation: { next_step: "no_action", package_id: null, urgency: "none", reason_test_ids: [], rule_id: "R0_all_normal", note: null },
  low_confidence_tests: [], warnings: [], metrics,
};

const abnormal: ReportResult = {
  ...normal, report_id: "demo_abnormal", panels: ["lipid"],
  tests: [
    t({ raw_name: "LDL Cholesterol", test_id: "ldl", panel: "lipid", flag: "high", severity: "marked", printed_flag: "H" }, 172, "mg/dL", 0, 130),
    t({ raw_name: "HDL Cholesterol", test_id: "hdl", panel: "lipid", flag: "low", severity: "mild" }, 36, "mg/dL", 40, 60),
    t({ raw_name: "Triglycerides", test_id: "triglycerides", panel: "lipid" }, 140, "mg/dL", 0, 150),
  ],
  patterns: ["Two lipid results are outside the printed ranges."],
  explanations: [
    { language: "en", source: "llm", urgent_message: null, summary: "Most results are within range. Two need attention.",
      statements: [
        { claim_id: "c1", text: "Your LDL is 172 mg/dL, above the usual range of up to 130 mg/dL.", cites: [{ kind: "test", id: "ldl" }] },
        { claim_id: "c2", text: "It's worth discussing these results with a doctor soon.", cites: [{ kind: "glossary", id: "ldl.high" }] }], disclaimer: disclaimerEn },
    { language: "hi", source: "llm", urgent_message: null, summary: "ज़्यादातर परिणाम सीमा में हैं। दो पर ध्यान देने की ज़रूरत है।",
      statements: [
        { claim_id: "c1", text: "आपका LDL 172 mg/dL है, जो 130 mg/dL तक की सामान्य सीमा से ऊपर है।", cites: [{ kind: "test", id: "ldl" }] },
        { claim_id: "c2", text: "इन परिणामों के बारे में जल्द ही डॉक्टर से बात करना अच्छा रहेगा।", cites: [{ kind: "glossary", id: "ldl.high" }] }], disclaimer: disclaimerHi },
  ],
  recommendation: { next_step: "doctor_consult", package_id: null, urgency: "soon", reason_test_ids: ["ldl", "hdl"], rule_id: "R2_marked", note: null },
};

const urgentEn = "One of your results is at a level that needs urgent medical attention. Please contact a doctor or go to the nearest emergency department today.";
const urgentHi = "आपका एक परिणाम ऐसे स्तर पर है जिस पर तुरंत चिकित्सा ध्यान देना ज़रूरी है। कृपया आज ही डॉक्टर से संपर्क करें या नज़दीकी इमरजेंसी विभाग जाएँ।";
const critical: ReportResult = {
  ...normal, report_id: "demo_critical", panels: ["cbc"],
  tests: [
    t({ raw_name: "Potassium", test_id: "potassium", panel: null, flag: "high", severity: "critical", is_critical: true, printed_flag: "H" }, 6.8, "mmol/L", 3.5, 5.1),
    t({ raw_name: "HGB", test_id: "hemoglobin", panel: "cbc" }, 13.0, "g/dL", 12, 15),
  ],
  explanations: [
    { language: "en", source: "template_fallback", urgent_message: urgentEn, summary: "One result needs urgent attention.",
      statements: [{ claim_id: "c1", text: "Your potassium is 6.8 mmol/L, above the usual range of 3.5 to 5.1 mmol/L.", cites: [{ kind: "test", id: "potassium" }] }], disclaimer: disclaimerEn },
    { language: "hi", source: "template_fallback", urgent_message: urgentHi, summary: "एक परिणाम पर तुरंत ध्यान देना ज़रूरी है।",
      statements: [{ claim_id: "c1", text: "आपका पोटैशियम 6.8 mmol/L है, जो 3.5 से 5.1 mmol/L की सामान्य सीमा से ऊपर है।", cites: [{ kind: "test", id: "potassium" }] }], disclaimer: disclaimerHi },
  ],
  recommendation: { next_step: "doctor_consult", package_id: null, urgency: "urgent", reason_test_ids: ["potassium"], rule_id: "R1_critical", note: null },
};

const held: ReportResult = {
  ...normal, report_id: "demo_held", status: "partial", panels: ["cbc"],
  tests: [
    t({ raw_name: "HGB", test_id: "hemoglobin", panel: "cbc", confidence: 0.55, flag: "unknown", severity: "unknown", warnings: ["unit_missing"] }, 11.2, null, 12, 15),
    t({ raw_name: "WBC", test_id: "wbc", panel: "cbc", page: 2 }, 6.4, "10^3/uL", 4, 11),
  ],
  unrecognised_tests: ["Serum Zeta Marker"],
  explanations: normal.explanations.map((e) => ({ ...e, source: "template_fallback" as const })),
  recommendation: { next_step: "doctor_consult", package_id: null, urgency: "routine", reason_test_ids: ["hemoglobin"], rule_id: "R5_unknown", note: null },
  low_confidence_tests: ["hemoglobin"],
  warnings: ["Hemoglobin has no unit printed, so it was not compared with the range.", "One test name was not recognised."],
};

const fixtures: Record<string, ReportResult> = { demo_normal: normal, demo_abnormal: abnormal, demo_critical: critical, demo_held: held };

export const demoReports: DemoReport[] = [
  { id: "demo_normal", title: "A balanced panel", description: "All values within the demonstration intervals.", category: "normal", test_count: 3, pdf_url: null },
  { id: "demo_abnormal", title: "Elevated cholesterol", description: "Two lipid markers outside range and a grounded follow-up suggestion.", category: "abnormal", test_count: 3, pdf_url: null },
  { id: "demo_critical", title: "Critical potassium", description: "A critical value: urgent guidance takes priority.", category: "critical", test_count: 2, pdf_url: null },
  { id: "demo_held", title: "Missing unit", description: "Held safely: a result has no reliable measurement unit.", category: "held", test_count: 2, pdf_url: null },
];

export async function getReport(id: string): Promise<ReportResult> {
  const r = fixtures[id];
  if (!r) throw new ApiError(404, "not_found", "Report not found or expired.");
  return delay(r);
}

export function createReport(_file: File, _type: string): Promise<ReportResult> {
  fixtures.upload_mock = { ...abnormal, report_id: "upload_mock" };
  return delay(fixtures.upload_mock, 800);
}
