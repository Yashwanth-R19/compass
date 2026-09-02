import { describe, expect, it } from "vitest";
import { findingDeepLink, parseHiddenDependencyPair, parseOsvId } from "./findingLinks";
import type { FindingOut } from "../api/types";

const REPO_ID = "repo-123";

function baseFinding(overrides: Partial<FindingOut>): FindingOut {
  return {
    id: "f1",
    category: "risk",
    severity: "high",
    confidence: 0.8,
    file_path: null,
    evidence_sha: null,
    title: "",
    detail: "",
    rank: 0,
    ...overrides,
  };
}

describe("parseHiddenDependencyPair", () => {
  it("parses OverlayEngine's exact title format", () => {
    expect(parseHiddenDependencyPair("Hidden dependency: src/a.py <-> src/b.py")).toEqual([
      "src/a.py",
      "src/b.py",
    ]);
  });

  it("returns null for a title that doesn't match the expected shape", () => {
    expect(parseHiddenDependencyPair("Something else entirely")).toBeNull();
  });
});

describe("parseOsvId", () => {
  it("parses SecurityEngine's exact title format", () => {
    expect(parseOsvId("GHSA-xxxx-yyyy-zzzz: requests@2.31.0")).toBe("GHSA-xxxx-yyyy-zzzz");
  });

  it("returns null when there's no colon to split on", () => {
    expect(parseOsvId("no colon here")).toBeNull();
  });
});

describe("findingDeepLink", () => {
  it("links a risk finding to that file's risk detail", () => {
    const link = findingDeepLink(baseFinding({ category: "risk", file_path: "src/a.py" }), REPO_ID);
    expect(link?.to).toBe(`/repos/${REPO_ID}/audit/risk?file=${encodeURIComponent("src/a.py")}`);
  });

  it("returns null for a risk finding with no file_path", () => {
    expect(findingDeepLink(baseFinding({ category: "risk", file_path: null }), REPO_ID)).toBeNull();
  });

  it("links a hidden_dependency finding to the coupling graph, hidden-only, with the pair", () => {
    const link = findingDeepLink(
      baseFinding({
        category: "hidden_dependency",
        file_path: "src/a.py",
        title: "Hidden dependency: src/a.py <-> src/b.py",
      }),
      REPO_ID,
    );
    expect(link?.to).toContain("/audit/coupling?");
    expect(link?.to).toContain("hiddenOnly=1");
    expect(link?.to).toContain(`pair=${encodeURIComponent("src/a.py|src/b.py")}`);
  });

  it("links a knowledge finding to People", () => {
    const link = findingDeepLink(
      baseFinding({ category: "knowledge", file_path: "src/a.py" }),
      REPO_ID,
    );
    expect(link?.to).toBe(
      `/repos/${REPO_ID}/onboard/people?path=${encodeURIComponent("src/a.py")}`,
    );
  });

  it("links a secret finding to Security with its commit sha", () => {
    const link = findingDeepLink(
      baseFinding({ category: "secret", evidence_sha: "abc123", file_path: "src/a.py" }),
      REPO_ID,
    );
    expect(link?.to).toContain("/audit/security?");
    expect(link?.to).toContain("sha=abc123");
  });

  it("links a vulnerability finding to Security with its parsed OSV id", () => {
    const link = findingDeepLink(
      baseFinding({ category: "vulnerability", title: "GHSA-xxxx: requests@2.31.0" }),
      REPO_ID,
    );
    expect(link?.to).toBe(`/repos/${REPO_ID}/audit/security?osv=GHSA-xxxx`);
  });

  it("builds every link as an ABSOLUTE /repos/<id>/... path", () => {
    const link = findingDeepLink(
      baseFinding({ category: "hygiene", file_path: "src/a.py" }),
      REPO_ID,
    );
    expect(link?.to.startsWith(`/repos/${REPO_ID}/`)).toBe(true);
  });
});
