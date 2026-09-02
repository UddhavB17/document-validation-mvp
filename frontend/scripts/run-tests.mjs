import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";

import ts from "typescript";

const testFiles = ["tests/format.test.ts", "tests/reviewUtils.test.ts"];
const outputDirectory = mkdtempSync(path.join(os.tmpdir(), "dmef-frontend-tests-"));

try {
  const program = ts.createProgram(testFiles, {
    target: ts.ScriptTarget.ES2020,
    module: ts.ModuleKind.CommonJS,
    moduleResolution: ts.ModuleResolutionKind.Node10,
    esModuleInterop: true,
    skipLibCheck: true,
    strict: true,
    baseUrl: process.cwd(),
    paths: { "@/*": ["./*"] },
    outDir: outputDirectory,
  });
  const emitResult = program.emit();
  const diagnostics = ts.getPreEmitDiagnostics(program).concat(emitResult.diagnostics);

  if (diagnostics.length > 0) {
    console.error(
      ts.formatDiagnosticsWithColorAndContext(diagnostics, {
        getCanonicalFileName: (fileName) => fileName,
        getCurrentDirectory: () => process.cwd(),
        getNewLine: () => "\n",
      }),
    );
    process.exitCode = 1;
  } else {
    const emittedTests = testFiles.map((file) =>
      path.join(outputDirectory, file.replace(/\.ts$/, ".js")),
    );
    const result = spawnSync(process.execPath, ["--test", ...emittedTests], { stdio: "inherit" });
    process.exitCode = result.status ?? 1;
  }
} finally {
  rmSync(outputDirectory, { recursive: true, force: true });
}
