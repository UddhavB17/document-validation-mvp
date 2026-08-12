import { z } from "zod";

export const uploadFormSchema = z.object({
  loanId: z.string().trim().min(1, "Loan ID is required"),
  applicantName: z.string().trim().min(1, "Applicant name is required"),
  coapplicantName: z.string().trim().optional(),
  productType: z.enum(["LAP", "MSME", "Personal Loan"]),
  branch: z.string().trim().min(1, "Branch is required"),
  caseType: z.enum(["Normal Case", "BT Case"]),
  applicationDate: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "Application date is required"),
  file: z.instanceof(File, { message: "PDF file is required" }).refine((file) => file.type === "application/pdf", {
    message: "Only PDF files are accepted",
  }),
});

export const decisionNoteSchema = z.string().trim().min(11, "Reviewer note must be more than 10 characters");
