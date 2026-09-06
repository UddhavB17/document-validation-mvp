import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

// Operations surfaces must stay free of technical internals: no text-reading
// engine names, no dumps, no internal ids, no processing-stage names.
const FORBIDDEN = [/ocr/i, /json/i, /rule_id/i, /pipeline/i];
const SCAN_DIRS = ["app/ops", "components/ops"];

function listFiles(dir: string): string[] {
  const entries = readdirSync(dir);
  const files: string[] = [];
  for (const entry of entries) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      files.push(...listFiles(full));
    } else if (/\.(ts|tsx)$/.test(entry)) {
      files.push(full);
    }
  }
  return files;
}

test("ops sources contain no technical internals", () => {
  const root = process.cwd();
  const offenders: string[] = [];
  for (const dir of SCAN_DIRS) {
    for (const file of listFiles(join(root, dir))) {
      const content = readFileSync(file, "utf-8");
      for (const pattern of FORBIDDEN) {
        if (pattern.test(content)) {
          offenders.push(`${file} matches ${pattern}`);
        }
      }
    }
  }
  assert.deepEqual(offenders, []);
});
