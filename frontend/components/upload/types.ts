import { UploadResponse } from "@/lib/api";

export type UploadTab = "pdf" | "mapped" | "json" | "zip";
export type CaseType = "Normal Case" | "BT Case";
export type UploadHandler = (result: UploadResponse) => void;

export interface UploadFormProps {
  onUploaded: UploadHandler;
}
