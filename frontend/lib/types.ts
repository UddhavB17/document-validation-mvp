import { z } from "zod";

/** Comparison field status shared across matrix rows and relationship nodes. */
export const comparisonStatusSchema = z.enum(["match", "mismatch", "attention"]);

export const fieldComparisonSchema = z.object({
  field_name: z.string(),
  label: z.string(),
  expected_value: z.string().nullable().optional(),
  extracted_value: z.string().nullable().optional(),
  status: comparisonStatusSchema,
  source_pages: z.array(z.number()),
});

export const applicantComparisonSchema = z.object({
  applicant_role: z.enum(["primary", "co_applicant", "guarantor"]),
  applicant_label: z.string(),
  person_name: z.string(),
  fields: z.array(fieldComparisonSchema),
});

export const comparisonMatrixSchema = z.object({
  core_parameters: z.array(fieldComparisonSchema),
  applicants: z.array(applicantComparisonSchema),
});

export const relationshipNodeSchema = z.object({
  id: z.string(),
  name: z.string(),
  role: z.enum(["primary", "co_applicant", "guarantor", "family_member"]),
  relation_to_primary: z.string().nullable().optional(),
  status: z.enum(["match", "mismatch", "attention", "n/a"]),
});

export const uploadedFileSchema = z
  .object({
    id: z.number().optional(),
    application_id: z.number().optional(),
    file_path: z.string().nullable().optional(),
    original_filename: z.string().nullable().optional(),
    file_size_kb: z.number().nullable().optional(),
    total_pages: z.number().nullable().optional(),
    digital_pages: z.number().nullable().optional(),
    scanned_pages: z.number().nullable().optional(),
    uploaded_at: z.string().nullable().optional(),
  })
  .passthrough();

export const applicationPageSchema = z
  .object({
    page_number: z.number().nullable().optional(),
    document_type: z.string().nullable().optional(),
    page_type: z.string().nullable().optional(),
    ocr_text: z.string().nullable().optional(),
    classification_confidence: z.number().nullable().optional(),
    extracted_fields: z.record(z.unknown()).optional(),
  })
  .passthrough();

export const manualReviewItemSchema = z.object({
  s_no: z.union([z.number(), z.string()]).nullable().optional(),
  description: z.string().nullable().optional(),
  category: z.string().nullable().optional(),
  document_type: z.string().nullable().optional(),
  reason: z.string().nullable().optional(),
});

export const documentSummarySchema = z.object({
  name: z.string(),
  type: z.string(),
  pages: z.string(),
  status: z.string(),
  firstPage: z.number(),
});

export const applicationRecordSchema = z
  .object({
    id: z.number().optional(),
    status: z.string().nullable().optional(),
    purpose: z.string().nullable().optional(),
    property_address: z.string().nullable().optional(),
    applicant_name: z.string().nullable().optional(),
    product_type: z.string().nullable().optional(),
    llm_summary: z.string().nullable().optional(),
    loan_id: z.string().nullable().optional(),
    branch: z.string().nullable().optional(),
    case_type: z.string().nullable().optional(),
  })
  .passthrough();

export const groundTruthSchema = z
  .object({
    applicant_name: z.string().nullable().optional(),
    raw_json: z.string().nullable().optional(),
    pan_number: z.string().nullable().optional(),
    loan_amount: z.string().nullable().optional(),
  })
  .passthrough();

export type ComparisonStatus = z.infer<typeof comparisonStatusSchema>;
export type FieldComparison = z.infer<typeof fieldComparisonSchema>;
export type ApplicantComparison = z.infer<typeof applicantComparisonSchema>;
export type ComparisonMatrix = z.infer<typeof comparisonMatrixSchema>;
export type RelationshipNode = z.infer<typeof relationshipNodeSchema>;
export type UploadedFile = z.infer<typeof uploadedFileSchema>;
export type ApplicationPage = z.infer<typeof applicationPageSchema>;
export type ManualReviewItem = z.infer<typeof manualReviewItemSchema>;
export type DocumentSummary = z.infer<typeof documentSummarySchema>;
export type ApplicationRecord = z.infer<typeof applicationRecordSchema>;
export type GroundTruth = z.infer<typeof groundTruthSchema>;

export type CaseType = "Normal Case" | "BT Case";
export type UploadTab = "pdf" | "mapped" | "json" | "zip";

/** Normalize applicants when the API returns an object map instead of an array. */
export function normalizeApplicantList(
  applicants: ApplicantComparison[] | Record<string, ApplicantComparison> | null | undefined,
): ApplicantComparison[] {
  if (Array.isArray(applicants)) {
    return applicants;
  }
  if (applicants && typeof applicants === "object") {
    return Object.values(applicants);
  }
  return [];
}

/** Count comparison fields that need reviewer attention (used in sidebar badge). */
export function countAttentionFields(matrix: ComparisonMatrix | null | undefined): number {
  const coreParams = matrix?.core_parameters ?? [];
  const applicantList = normalizeApplicantList(matrix?.applicants);
  const allFields = [...coreParams, ...applicantList.flatMap((applicant) => applicant.fields)];
  return allFields.filter((field) => field.status === "mismatch" || field.status === "attention").length;
}
