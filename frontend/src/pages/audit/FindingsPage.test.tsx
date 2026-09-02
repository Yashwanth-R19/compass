import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FindingsPage } from "./FindingsPage";
import type { FindingOut } from "../../api/types";
import type { RepoOutletContext } from "../RepoLayout";

const useFindingsMock = vi.fn();

vi.mock("../../api/hooks", () => ({
  useFindings: (...args: unknown[]) => useFindingsMock(...args),
}));

function finding(overrides: Partial<FindingOut>): FindingOut {
  return {
    id: "id",
    category: "risk",
    severity: "med",
    confidence: 0.8,
    file_path: null,
    evidence_sha: null,
    title: "",
    detail: "",
    rank: 0,
    ...overrides,
  };
}

const REPO_CONTEXT: RepoOutletContext = {
  repo: {
    id: "repo-1",
    url: "https://github.com/o/n",
    owner: "o",
    name: "n",
    default_branch: "main",
    status: "ready",
    commit_count: 10,
    analyzed_at: null,
    created_at: "2026-01-01T00:00:00Z",
    file_count: 5,
    is_private: false,
  },
  share: undefined,
};

function renderFindingsPage(findings: FindingOut[]) {
  useFindingsMock.mockReturnValue({
    isPending: false,
    isError: false,
    data: { kind: "data", data: { repo_id: "repo-1", findings } },
    refetch: vi.fn(),
  });

  render(
    <MemoryRouter initialEntries={["/repos/repo-1/audit/findings"]}>
      <Routes>
        <Route path="repos/:repoId" element={<Outlet context={REPO_CONTEXT} />}>
          <Route path="audit/findings" element={<FindingsPage />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("FindingsPage -- the subtractive default (RULES.md sec 12, Known Hazard #2)", () => {
  beforeEach(() => {
    useFindingsMock.mockReset();
  });

  it("shows exactly 10 rows by default when there are more than 10 findings", () => {
    const findings = Array.from({ length: 15 }, (_, i) =>
      finding({ id: String(i), title: `Finding ${i}`, rank: i }),
    );
    renderFindingsPage(findings);

    expect(screen.getAllByText(/^Finding \d+$/)).toHaveLength(10);
    expect(screen.getByText("Show all 15 findings")).toBeTruthy();
  });

  it("reveals every finding once 'show all' is clicked, and can collapse back", () => {
    const findings = Array.from({ length: 15 }, (_, i) =>
      finding({ id: String(i), title: `Finding ${i}`, rank: i }),
    );
    renderFindingsPage(findings);

    fireEvent.click(screen.getByText("Show all 15 findings"));
    expect(screen.getAllByText(/^Finding \d+$/)).toHaveLength(15);

    fireEvent.click(screen.getByText("Show top 10 only"));
    expect(screen.getAllByText(/^Finding \d+$/)).toHaveLength(10);
  });

  it("shows no 'show all' affordance when there are 10 or fewer findings", () => {
    const findings = Array.from({ length: 4 }, (_, i) =>
      finding({ id: String(i), title: `Finding ${i}`, rank: i }),
    );
    renderFindingsPage(findings);

    expect(screen.getAllByText(/^Finding \d+$/)).toHaveLength(4);
    expect(screen.queryByText(/Show all/)).toBeNull();
  });
});

describe("FindingsPage -- never re-sorts (Known Hazard #1)", () => {
  beforeEach(() => {
    useFindingsMock.mockReset();
  });

  it("renders findings in the exact order the backend returned them, even when severity is deliberately out of order", () => {
    // Deliberately NOT sorted by severity (med, high, low, high, low...) --
    // a client-side severity sort would visibly reorder this list. The
    // backend's `rank` field is what determines order; this array's OWN
    // position is what must be preserved.
    const shuffled: FindingOut[] = [
      finding({ id: "a", title: "Finding A", severity: "med", rank: 0 }),
      finding({ id: "b", title: "Finding B", severity: "high", rank: 1 }),
      finding({ id: "c", title: "Finding C", severity: "low", rank: 2 }),
      finding({ id: "d", title: "Finding D", severity: "high", rank: 3 }),
      finding({ id: "e", title: "Finding E", severity: "low", rank: 4 }),
    ];
    renderFindingsPage(shuffled);

    const rendered = screen.getAllByText(/^Finding [A-E]$/).map((el) => el.textContent);
    expect(rendered).toEqual(["Finding A", "Finding B", "Finding C", "Finding D", "Finding E"]);
  });

  it("filtering by severity removes rows without reordering what remains", () => {
    const shuffled: FindingOut[] = [
      finding({ id: "a", title: "Finding A", severity: "high", rank: 0 }),
      finding({ id: "b", title: "Finding B", severity: "med", rank: 1 }),
      finding({ id: "c", title: "Finding C", severity: "high", rank: 2 }),
      finding({ id: "d", title: "Finding D", severity: "low", rank: 3 }),
      finding({ id: "e", title: "Finding E", severity: "high", rank: 4 }),
    ];
    renderFindingsPage(shuffled);

    fireEvent.change(screen.getByDisplayValue("All severities"), { target: { value: "high" } });

    const rendered = screen.getAllByText(/^Finding [A-E]$/).map((el) => el.textContent);
    expect(rendered).toEqual(["Finding A", "Finding C", "Finding E"]);
  });
});
