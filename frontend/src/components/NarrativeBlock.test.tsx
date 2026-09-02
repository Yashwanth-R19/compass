import { render, screen } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NarrativeBlock } from "./NarrativeBlock";
import type { RepoOutletContext } from "../pages/RepoLayout";

const useNarrativeMock = vi.fn();
const useNarrativeEnabledMock = vi.fn();

vi.mock("../api/hooks", () => ({
  useNarrative: (...args: unknown[]) => useNarrativeMock(...args),
}));

vi.mock("../lib/narrativePref", () => ({
  useNarrativeEnabled: () => useNarrativeEnabledMock(),
}));

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

function renderBlock() {
  return render(
    <MemoryRouter initialEntries={["/repos/repo-1/onboard/passport"]}>
      <Routes>
        <Route path="repos/:repoId" element={<Outlet context={REPO_CONTEXT} />}>
          <Route path="onboard/passport" element={<NarrativeBlock surface="passport" />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  useNarrativeMock.mockReset();
  useNarrativeEnabledMock.mockReset();
});

describe("NarrativeBlock", () => {
  it("renders nothing when the global toggle is off, regardless of what the query would return", () => {
    useNarrativeEnabledMock.mockReturnValue(false);
    useNarrativeMock.mockReturnValue({
      isPending: false,
      isFetching: false,
      isError: false,
      data: { available: true, content: "Should never appear.", provider: "gemini", model: "m" },
    });

    const { container } = renderBlock();
    expect(container.innerHTML).toBe("");
  });

  it("collapses to nothing while loading -- no spinner, no layout reservation (Known Hazard #6)", () => {
    useNarrativeEnabledMock.mockReturnValue(true);
    useNarrativeMock.mockReturnValue({
      isPending: true,
      isFetching: true,
      isError: false,
      data: undefined,
    });

    const { container } = renderBlock();
    expect(container.innerHTML).toBe("");
  });

  it("renders a quiet unavailable line when the API says unavailable -- no alarming styling", () => {
    useNarrativeEnabledMock.mockReturnValue(true);
    useNarrativeMock.mockReturnValue({
      isPending: false,
      isFetching: false,
      isError: false,
      data: { available: false, content: null, provider: null, model: null, reason: "no_keys" },
    });

    renderBlock();
    expect(screen.getByText(/narrative unavailable/i)).toBeTruthy();
  });

  it("renders the quiet unavailable line on a query error too, never a scary error banner", () => {
    useNarrativeEnabledMock.mockReturnValue(true);
    useNarrativeMock.mockReturnValue({
      isPending: false,
      isFetching: false,
      isError: true,
      data: undefined,
    });

    renderBlock();
    expect(screen.getByText(/narrative unavailable/i)).toBeTruthy();
  });

  it("renders the generated content with the required label and provider/model, visually distinct", () => {
    useNarrativeEnabledMock.mockReturnValue(true);
    useNarrativeMock.mockReturnValue({
      isPending: false,
      isFetching: false,
      isError: false,
      data: {
        available: true,
        content: "This repository has moderate risk concentration.",
        provider: "gemini",
        model: "gemini-2.0-flash",
        generated_at: "2026-01-01T00:00:00Z",
        reason: null,
      },
    });

    const { container } = renderBlock();
    expect(screen.getByText("This repository has moderate risk concentration.")).toBeTruthy();
    expect(screen.getByText(/generated phrasing/i)).toBeTruthy();
    expect(screen.getByText(/the numbers are computed/i)).toBeTruthy();
    expect(screen.getByText(/gemini\/gemini-2.0-flash/i)).toBeTruthy();
    // Visually distinct container, per the session's own requirement --
    // never the same neutral surface every other card on the page uses.
    expect(container.innerHTML).toContain("violet");
  });
});
