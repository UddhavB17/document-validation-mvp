import { UploadTab } from "./types";

export const UPLOAD_TABS: ReadonlyArray<{ value: UploadTab; label: string }> = [
  { value: "zip", label: "ZIP Package Intake" },
  { value: "mapped", label: "Mapped Verification" },
];
