import { render, screen } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PeoplePage } from "./PeoplePage";
import { TooltipProvider } from "../../components/ui/Tooltip";
import type {
  ContributorsResponse,
  ExpertiseResponse,
  KnowledgeMapResponse,
  TruckFactorResponse,
} from "../../api/types";
import type { RepoOutletContext } from "../RepoLayout";

// plan/RULES.md section 11 -- no email, masked or full, may ever be
// rendered on this page. Every fixture below deliberately embeds a real
// "@" in every masked-email field a careless render could leak, so this
// test genuinely proves the component never touches those fields rather
// than merely proving it doesn't touch a field the fixture left blank.

const useContributorsMock = vi.fn();
const useExpertiseMock = vi.fn();
const useKnowledgeMapMock = vi.fn();
const useTruckFactorMock = vi.fn();
const useFormulasMock = vi.fn();

vi.mock("../../api/hooks", () => ({
  useContributors: (...args: unknown[]) => useContributorsMock(...args),
  useExpertise: (...args: unknown[]) => useExpertiseMock(...args),
  useKnowledgeMap: (...args: unknown[]) => useKnowledgeMapMock(...args),
  useTruckFactor: (...args: unknown[]) => useTruckFactorMock(...args),
  useFormulas: (...args: unknown[]) => useFormulasMock(...args),
}));

const REPO_CONTEXT: RepoOutletContext = {
  repo: {
    id: "repo-1",
    url: "https://github.com/o/n",
    owner: "o",
    name: "n",
    default_branch: "main",
    status: "ready",
    commit_count: 40,
    analyzed_at: null,
    created_at: "2026-01-01T00:00:00Z",
    file_count: 12,
    is_private: false,
    is_showcase: false,
  },
  share: undefined,
};

const CONTRIBUTORS: ContributorsResponse = {
  repo_id: "repo-1",
  contributors: [
    {
      id: 1,
      canonical_name: "Jane Doe",
      canonical_email_masked: "j***e@e***e.com",
      aliases: [
        { name: "Jane Doe", email_masked: "j***e@e***e.com" },
        { name: "jdoe", email_masked: "j***e@w***k.com" },
      ],
      commit_count: 80,
      lines_added: 4000,
      lines_deleted: 900,
      first_commit_at: "2024-01-01T00:00:00Z",
      last_commit_at: "2026-01-01T00:00:00Z",
      is_bot: false,
      active_days: 120,
      is_stale: false,
      rank: 0,
    },
    {
      id: 2,
      canonical_name: "dependabot[bot]",
      canonical_email_masked: "d***t@u***s.com",
      aliases: [],
      commit_count: 20,
      lines_added: 500,
      lines_deleted: 100,
      first_commit_at: "2024-06-01T00:00:00Z",
      last_commit_at: "2025-06-01T00:00:00Z",
      is_bot: true,
      active_days: 40,
      is_stale: true,
      rank: 1,
    },
  ],
};

const KNOWLEDGE_MAP: KnowledgeMapResponse = {
  repo_id: "repo-1",
  files: [
    {
      file_path: "src/app.py",
      principal_expert_contributor_id: 1,
      doa_normalized: 0.9,
      subsystem_id: null,
    },
  ],
  contributors: [
    {
      id: 1,
      canonical_name: "Jane Doe",
      canonical_email_masked: "j***e@e***e.com",
      is_bot: false,
      is_stale: false,
    },
  ],
};

const EXPERTISE: ExpertiseResponse = {
  repo_id: "repo-1",
  file_path: "src/app.py",
  experts: [
    {
      contributor_id: 1,
      canonical_name: "Jane Doe",
      canonical_email_masked: "j***e@e***e.com",
      doa: 4.1,
      doa_normalized: 0.95,
      is_expert: true,
      changes: 12,
      last_touched_at: "2026-01-01T00:00:00Z",
      is_stale: false,
    },
  ],
};

const TRUCK_FACTOR: TruckFactorResponse = {
  repo_id: "repo-1",
  value: 2,
  removal_order: [
    { contributor_id: 1, name: "Jane Doe", files_orphaned: 5, cumulative_orphan_ratio: 0.4 },
  ],
  total_files_considered: 12,
  orphaned_file_count: 0,
  note: null,
  interpretation: "This measures the project's own knowledge-distribution risk.",
};

function renderPeoplePage(initialPath = "/repos/repo-1/people") {
  useContributorsMock.mockReturnValue({
    isPending: false,
    isError: false,
    data: { kind: "data", data: CONTRIBUTORS },
    refetch: vi.fn(),
  });
  useKnowledgeMapMock.mockReturnValue({
    isPending: false,
    isError: false,
    data: { kind: "data", data: KNOWLEDGE_MAP },
    refetch: vi.fn(),
  });
  useExpertiseMock.mockReturnValue({
    isPending: false,
    isError: false,
    data: { kind: "data", data: EXPERTISE },
    refetch: vi.fn(),
  });
  useTruckFactorMock.mockReturnValue({
    isPending: false,
    isError: false,
    data: { kind: "data", data: TRUCK_FACTOR },
    refetch: vi.fn(),
  });
  useFormulasMock.mockReturnValue({ data: undefined, isPending: false, isError: false });

  render(
    <TooltipProvider>
      <MemoryRouter initialEntries={[`${initialPath}?path=src%2Fapp.py`]}>
        <Routes>
          <Route path="repos/:repoId" element={<Outlet context={REPO_CONTEXT} />}>
            <Route path="people" element={<PeoplePage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </TooltipProvider>,
  );
}

describe("PeoplePage -- privacy (plan/RULES.md sec 11, non-negotiable)", () => {
  beforeEach(() => {
    useContributorsMock.mockReset();
    useExpertiseMock.mockReset();
    useKnowledgeMapMock.mockReset();
    useTruckFactorMock.mockReset();
    useFormulasMock.mockReset();
  });

  it("never renders an '@' character anywhere on the page, even though every fixture's masked email fields contain one", () => {
    renderPeoplePage();

    // Sanity check the fixtures themselves actually contain '@' -- a test
    // that can't fail this way would prove nothing.
    expect(CONTRIBUTORS.contributors[0].canonical_email_masked).toContain("@");
    expect(CONTRIBUTORS.contributors[0].aliases[0].email_masked).toContain("@");
    expect(EXPERTISE.experts[0].canonical_email_masked).toContain("@");

    expect(document.body.textContent).not.toContain("@");
  });

  it("shows contributors as a plain list -- no rank numerals, medals, or '#1' framing", () => {
    renderPeoplePage();
    expect(screen.getAllByText("Jane Doe").length).toBeGreaterThan(0);
    expect(screen.queryByText("#1")).toBeNull();
    expect(screen.queryByText(/top contributor/i)).toBeNull();
    // The page's own copy explicitly DISCLAIMS a productivity framing
    // ("not a productivity score") -- that is the correct usage of the
    // word, so this asserts no POSITIVE productivity/performance claim
    // exists (e.g. "productivity score:", "top performer"), not that the
    // word never appears at all.
    expect(screen.queryByText(/contribution score/i)).toBeNull();
    expect(screen.queryByText(/top performer/i)).toBeNull();
  });

  it("renders the truck-factor interpretation verbatim", () => {
    renderPeoplePage();
    expect(
      screen.getByText("This measures the project's own knowledge-distribution risk."),
    ).toBeTruthy();
  });
});
