import { ZodError } from "zod";

import { CaseType } from "./types";

export const CASE_TYPE_OPTIONS: readonly CaseType[] = ["Normal Case", "BT Case"];

export function getCaseType(value: unknown): CaseType {
  return value === "BT Case" ? "BT Case" : "Normal Case";
}

export function getFormError(error: unknown): string {
  if (error instanceof ZodError) {
    return error.errors.map((item) => item.message).join("; ");
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Request failed";
}

export function isPdfFile(file: File): boolean {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function escapeControlCharacters(jsonString: string): string {
  return jsonString.replace(/"([^"\\]|\\.)*"/g, (match) => {
    return match.replace(/[\x00-\x1f]/g, (char) => {
      if (char === "\n") return "\\n";
      if (char === "\r") return "\\r";
      if (char === "\t") return "\\t";
      const hex = char.charCodeAt(0).toString(16).padStart(4, "0");
      return "\\u" + hex;
    });
  });
}

export function getSanitizedManifest(text: string): string {
  const trimmed = text.trim();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    const escaped = escapeControlCharacters(trimmed);
    try {
      JSON.parse(escaped);
      return escaped;
    } catch {
      // The backend accepts smart quotes, truncated braces, and database dumps.
      return trimmed;
    }
  }
  return trimmed;
}

export function inferDocumentType(filename: string): string {
  const lower = filename.toLowerCase().replace(/\\/g, "/");

  if (lower.includes("pan")) return "PAN Card";
  if (lower.includes("aadhar") || lower.includes("aadhaar") || lower.includes("uidai")) return "Aadhaar Card";
  if (lower.includes("passport")) return "Passport";
  if (lower.includes("driving") || lower.includes("dl ") || lower.includes(" licence") || lower.includes(" license")) return "Driving License";
  if (lower.includes("voter") || lower.includes("epic")) return "Voter ID";
  if (lower.includes("cheque") || lower.includes("check")) return "Cheque";
  if (lower.includes("statement") || lower.includes("bank_stmt") || lower.includes("bank stmt") || lower.includes("bankstmt")) return "Bank Statement";
  if (lower.includes("utility") || lower.includes("bill") || lower.includes("electricity") || lower.includes("water") || lower.includes("gas_bill")) return "Utility Bill";
  if (lower.includes("sanction") || lower.includes("loan_sanction")) return "Sanction Letter";
  if (lower.includes("agreement") || lower.includes("contract") || lower.includes("loan_agreement")) return "Loan Agreement";
  if (lower.includes("salary") || lower.includes("pay slip") || lower.includes("payslip") || lower.includes("salary_slip")) return "Salary Slip";
  if (lower.includes("kfs") || lower.includes("key fact")) return "KFS (Key Fact Statement)";

  const parts = lower.split("/");
  const sourceName = parts.length > 1 ? parts[parts.length - 2] : parts[parts.length - 1].replace(/\.[^/.]+$/, "");
  return sourceName.replace(/[_-]/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}
