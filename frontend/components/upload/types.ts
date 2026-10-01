import { UploadResponse } from "@/lib/api";

// These are the supported intake modes in the primary admin workflow. The
// legacy PDF and partner JSON endpoints remain available to the backend and
// their form components, but are intentionally not exposed as tabs here.
export type UploadTab = "zip" | "mapped";
export type CaseType = "Normal Case" | "BT Case";
export type UploadHandler = (result: UploadResponse) => void;

export interface UploadFormProps {
  onUploaded: UploadHandler;
  onFlowStart?: () => void;
  onBusyChange?: (busy: boolean) => void;
}
