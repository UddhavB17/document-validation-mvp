import assert from "node:assert/strict";
import test from "node:test";

import {
  EVIDENCE_PROXY_PREFIX,
  evidenceBackendPath,
  evidenceProxyErrorDetail,
  evidenceProxyOcrJsonUrl,
  evidenceProxyPageImageUrl,
  evidenceProxyPdfUrl,
  mapEvidenceBackendErrorStatus,
  parseEvidenceProxyPath,
  parseEvidenceProxyRequest,
  resolveEvidenceBackendBase,
} from "../lib/evidenceProxy";

function params(query: string): URLSearchParams {
  return new URLSearchParams(query);
}

test("parses the three allowlisted evidence paths", () => {
  assert.deepEqual(parseEvidenceProxyPath(["review", "applications", "12", "source-pdf"]), {
    kind: "source-pdf",
    applicationId: 12,
  });
  assert.deepEqual(parseEvidenceProxyPath(["review", "applications", "7", "ocr-json"]), {
    kind: "ocr-json",
    applicationId: 7,
  });
  assert.deepEqual(
    parseEvidenceProxyPath(["review", "applications", "3", "source-page", "9"]),
    { kind: "source-page", applicationId: 3, pageNumber: 9 },
  );
});

test("rejects non-allowlisted paths without touching the backend", () => {
  const bad: string[][] = [
    [],
    ["review"],
    ["review", "applications", "12"],
    ["review", "applications", "12", "source-page"],
    ["review", "applications", "12", "source-pdf", "extra"],
    ["review", "applications", "12", "pages", "1"],
    ["review", "applications", "12", "source-page", "1", "extra"],
    ["ops", "applications", "12", "source-pdf"],
    ["review", "applications", "abc", "source-pdf"],
    ["review", "applications", "0", "source-pdf"],
    ["review", "applications", "-4", "ocr-json"],
    ["review", "applications", "12", "source-page", "0"],
    ["review", "applications", "12", "source-page", "-2"],
    ["review", "applications", "12", "source-page", "1.5"],
    ["review", "applications", "12", "source-page", ".."],
    ["review", "applications", "..", "source-pdf"],
    ["review", "applications", "12", ".."],
  ];
  for (const segments of bad) {
    assert.equal(parseEvidenceProxyPath(segments), null, JSON.stringify(segments));
    const parsed = parseEvidenceProxyRequest(segments, params(""));
    assert.equal(parsed.ok, false, JSON.stringify(segments));
    if (!parsed.ok) {
      assert.equal(parsed.status, 404);
    }
  }
});

test("forwards only the allowlisted source-page query parameters", () => {
  const parsed = parseEvidenceProxyRequest(
    ["review", "applications", "3", "source-page", "9"],
    params("highlight=Pancard&dpi=150"),
  );
  assert.equal(parsed.ok, true);
  if (parsed.ok) {
    assert.equal(parsed.value.highlight, "Pancard");
    assert.equal(parsed.value.dpi, 150);
    assert.equal(
      evidenceBackendPath(parsed.value),
      "/review/applications/3/source-page/9?highlight=Pancard&dpi=150",
    );
  }

  // Unknown parameters (token smuggling, destination URLs, backend flags)
  // are stripped and never reach the backend path.
  const stripped = parseEvidenceProxyRequest(
    ["review", "applications", "3", "source-page", "9"],
    params("highlight=abc&token=evil&url=https%3A%2F%2Fx&redirect=%2Fadmin&dpi=200"),
  );
  assert.equal(stripped.ok, true);
  if (stripped.ok) {
    assert.equal(
      evidenceBackendPath(stripped.value),
      "/review/applications/3/source-page/9?highlight=abc&dpi=200",
    );
  }

  // source-pdf / ocr-json take no query parameters at all.
  const pdf = parseEvidenceProxyRequest(
    ["review", "applications", "5", "source-pdf"],
    params("highlight=abc&dpi=150&token=evil"),
  );
  assert.equal(pdf.ok, true);
  if (pdf.ok) {
    assert.equal(evidenceBackendPath(pdf.value), "/review/applications/5/source-pdf");
  }
  const ocr = parseEvidenceProxyRequest(
    ["review", "applications", "5", "ocr-json"],
    params("dpi=150"),
  );
  assert.equal(ocr.ok, true);
  if (ocr.ok) {
    assert.equal(evidenceBackendPath(ocr.value), "/review/applications/5/ocr-json");
  }
});

test("rejects out-of-range dpi and caps highlight length", () => {
  for (const dpi of ["abc", "10", "71", "289", "1000", "150.5", "-150"]) {
    const parsed = parseEvidenceProxyRequest(
      ["review", "applications", "3", "source-page", "9"],
      params(`dpi=${dpi}`),
    );
    assert.equal(parsed.ok, false, `dpi=${dpi}`);
    if (!parsed.ok) {
      assert.equal(parsed.status, 400);
    }
  }

  const long = parseEvidenceProxyRequest(
    ["review", "applications", "3", "source-page", "9"],
    params(`highlight=${"x".repeat(2000)}`),
  );
  assert.equal(long.ok, true);
  if (long.ok) {
    assert.equal(long.value.highlight?.length, 1000);
  }
});

test("proxy URL builders stay same-origin and token-free", () => {
  const pdf = evidenceProxyPdfUrl(12, 4);
  assert.equal(pdf, `${EVIDENCE_PROXY_PREFIX}/review/applications/12/source-pdf#page=4&zoom=page-width`);
  assert.equal(evidenceProxyPdfUrl(12), `${EVIDENCE_PROXY_PREFIX}/review/applications/12/source-pdf`);

  const image = evidenceProxyPageImageUrl(3, 9, "Pan Card");
  assert.equal(
    image,
    `${EVIDENCE_PROXY_PREFIX}/review/applications/3/source-page/9?highlight=Pan%20Card`,
  );
  assert.equal(
    evidenceProxyPageImageUrl(3, 9),
    `${EVIDENCE_PROXY_PREFIX}/review/applications/3/source-page/9`,
  );

  assert.equal(
    evidenceProxyOcrJsonUrl(7),
    `${EVIDENCE_PROXY_PREFIX}/review/applications/7/ocr-json`,
  );

  for (const url of [pdf, image, evidenceProxyOcrJsonUrl(7)]) {
    assert.ok(url.startsWith("/api/evidence/"), url);
    assert.ok(!url.includes("http"), url);
    assert.ok(!/bearer/i.test(url), url);
    assert.ok(!/token/i.test(url), url);
  }
});

test("backend error statuses map to safe proxy statuses", () => {
  assert.equal(mapEvidenceBackendErrorStatus(401), 401);
  assert.equal(mapEvidenceBackendErrorStatus(403), 403);
  assert.equal(mapEvidenceBackendErrorStatus(404), 404);
  // Redirects, validation failures, and server errors never leak through.
  for (const status of [301, 302, 400, 422, 500, 502, 503]) {
    assert.equal(mapEvidenceBackendErrorStatus(status), 502, `status=${status}`);
  }
  assert.equal(evidenceProxyErrorDetail(401), "Not authenticated");
  assert.equal(evidenceProxyErrorDetail(403), "Forbidden");
  assert.equal(evidenceProxyErrorDetail(404), "Evidence not found");
  assert.equal(evidenceProxyErrorDetail(502), "Evidence backend unavailable");
});

test("backend base prefers explicit value and trims slashes", () => {
  assert.equal(resolveEvidenceBackendBase("https://api.example.com/"), "https://api.example.com");
  assert.equal(
    resolveEvidenceBackendBase("http://127.0.0.1:8000///"),
    "http://127.0.0.1:8000",
  );
});
