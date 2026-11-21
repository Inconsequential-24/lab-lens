// Thin typed client over the generated OpenAPI types (src/api/schema.d.ts, `npm run gen:api`).
import type { components } from "./schema";
import * as mock from "./mock";

export type ReportResult = components["schemas"]["ReportResult"];
export type FlaggedTest = components["schemas"]["FlaggedTest"];
export type Explanation = components["schemas"]["Explanation"];
export type ApiErrorBody = components["schemas"]["Error"];
export type UploadRequest = components["schemas"]["UploadRequest"];

export type DemoCategory = "normal" | "abnormal" | "critical" | "held";
export interface DemoReport {
  id: string;
  title: string;
  description: string;
  category: DemoCategory;
  test_count: number;
  pdf_url: string | null;
}
export type ApiDemoReport = components["schemas"]["DemoReport"];
export type SavedReport = components["schemas"]["SavedReport"];
export type SaveRequest = components["schemas"]["SaveRequest"];
export type OverlapItem = components["schemas"]["OverlapItem"];
export type ConflictError = components["schemas"]["ConflictError"];
export type TrendResponse = components["schemas"]["TrendResponse"];
export type TrendPoint = components["schemas"]["TrendPoint"];
export const NOTICE_VERSION = "2026-11-v1";
const DEMO_ID = /^D\d{2}$/;
const PANEL_TEXT: Record<string, string> = {
  cbc: "Complete blood count", lipid: "Lipid profile", hba1c: "HbA1c (average blood sugar)",
  thyroid: "Thyroid profile", lft: "Liver function tests",
};

export const MOCK = import.meta.env.VITE_MOCK === "1";
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

import { ApiError } from "./errors";
import { getToken } from "../auth";
export { ApiError };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, { ...init, headers: { Accept: "application/json", ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}), ...init?.headers } });
  } catch {
    throw new ApiError(0, "network", "Could not reach the LabLens service.");
  }
  const body: unknown = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const err = body as Partial<ApiErrorBody> | null;
    throw new ApiError(res.status, err?.reason ?? "unknown", err?.message ?? `Request failed (${res.status}).`, body);
  }
  return body as T;
}

export function listDemoReports(): Promise<DemoReport[]> {
  const list = MOCK ? mock.listDemoReports() : request<{ reports: ApiDemoReport[] }>("/v1/demo/reports");
  // Mock and real return the same API shape; both are mapped here to DemoReport.
  return list.then(({ reports }) =>
    reports.map(({ panel, ...r }) => ({
      ...r,
      description: `${PANEL_TEXT[panel ?? ""] ?? "Synthetic lab report"} · synthetic demo report`,
    })),
  );
}

// A demo is a synthetic source PDF: it is uploaded like any synthetic report, and the
// server's response cache answers repeat opens without a new model call.
async function openDemo(demoId: string): Promise<ReportResult> {
  let pdf: Response;
  try {
    pdf = await fetch(`${BASE}/v1/demo/reports/${demoId}.pdf`);
  } catch {
    throw new ApiError(0, "network", "Could not reach the LabLens service.");
  }
  if (!pdf.ok) throw new ApiError(pdf.status, "not_found", "This demo report is not available.");
  const file = new File([await pdf.blob()], `${demoId}.pdf`, { type: "application/pdf" });
  return createReport(file, "synthetic");
}

export function getReport(reportId: string): Promise<ReportResult> {
  if (MOCK) return mock.getReport(reportId);
  if (DEMO_ID.test(reportId)) return openDemo(reportId);
  return request<ReportResult>(`/v1/reports/${encodeURIComponent(reportId)}`);
}

export function createReport(
  file: File,
  reportType: NonNullable<UploadRequest["report_type"]>,
  language: NonNullable<UploadRequest["language"]> = "both",
): Promise<ReportResult> {
  if (MOCK) return mock.createReport(file, reportType);
  const form = new FormData();
  form.append("file", file);
  form.append("language", language);
  form.append("report_type", reportType);
  return request<ReportResult>("/v1/reports", { method: "POST", body: form });
}

// Client-side pre-checks; the server re-checks by content.
export const MAX_BYTES = 10 * 1024 * 1024;
export const ACCEPTED_TYPES = ["application/pdf", "image/png", "image/jpeg"];
export function checkFile(file: File): "unsupported_file_type" | "file_too_large" | null {
  if (!ACCEPTED_TYPES.includes(file.type)) return "unsupported_file_type";
  if (file.size > MAX_BYTES) return "file_too_large";
  if (file.size === 0) return "unsupported_file_type";
  return null;
}

// ---- Opt-in history (PLAN section 10); all need a Google ID token. ----
export function saveReport(reportId: string, body: SaveRequest): Promise<SavedReport> {
  if (MOCK) return mock.saveReport(reportId, body);
  return request<SavedReport>(`/v1/reports/${encodeURIComponent(reportId)}/save`, {
    method: "POST", body: JSON.stringify(body), headers: { "Content-Type": "application/json" },
  });
}
export function listHistory(): Promise<SavedReport[]> {
  if (MOCK) return mock.listHistory();
  return request<{ reports: SavedReport[] }>("/v1/history").then((r) => r.reports);
}
export function getTrend(testId: string): Promise<TrendResponse> {
  if (MOCK) return mock.getTrend(testId);
  return request<TrendResponse>(`/v1/history/trends?test_id=${encodeURIComponent(testId)}`);
}
export function deleteHistoryItem(savedReportId: string): Promise<void> {
  if (MOCK) return mock.deleteHistoryItem(savedReportId);
  return request<null>(`/v1/history/${encodeURIComponent(savedReportId)}`, { method: "DELETE" }).then(() => undefined);
}
export function deleteAllHistory(): Promise<void> {
  if (MOCK) return mock.deleteAllHistory();
  return request<null>("/v1/history", { method: "DELETE" }).then(() => undefined);
}
