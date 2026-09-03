import { expect, test, type Route } from "@playwright/test";
import {
  REPO_ID,
  architectureResponse,
  couplingResponse,
  findingsResponse,
  formulasResponse,
  healthResponse,
  hiddenDependenciesResponse,
  hygieneResponseEmpty,
  moduleCouplingSubsystemResponse,
  passportResponse,
  pipelineResponse,
  repoOut,
  repoStatus,
  riskResponse,
  runsResponse,
  secretsResponseEmpty,
  showcaseReposResponse,
  subsystemsResponse,
  testGapsResponseEmpty,
  vulnerabilitiesResponseEmptyPrimary,
} from "./fixtures";

const API_URL = "http://localhost:8000";

// One Playwright test, not a suite (UI rebuild session 4, Part G): the
// product works end to end against a mocked API, on the NEW 8-surface
// route map (section 4.1) -- landing (a showcase card is visible) into a
// repository's Overview, then Map (expand and collapse a subsystem), then
// Findings (open a finding's evidence panel and follow its deep link to
// the destination surface), then Risk (expand a hotspot row and open its
// ScoreExplainer). Every backend call this flow can make is routed here
// explicitly; anything unmatched falls through to a 404 fixture rather
// than a real network call, so a missed mock fails loudly (a hung/failed
// request) instead of silently hitting localhost:8000.
test("Compass: landing -> Overview -> Map -> Findings -> Risk", async ({ page }) => {
  await page.route(`${API_URL}/**`, (route: Route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;

    if (path === "/auth/me") {
      return route.fulfill({ status: 401, json: { detail: "Not authenticated" } });
    }
    if (path === "/repos/showcase") {
      return route.fulfill({ json: showcaseReposResponse });
    }
    if (path === "/meta/formulas") {
      return route.fulfill({ json: formulasResponse });
    }
    if (path === "/meta/pipeline") {
      return route.fulfill({ json: pipelineResponse });
    }

    if (path === `/repos/${REPO_ID}`) {
      return route.fulfill({ json: repoOut });
    }
    if (path === `/repos/${REPO_ID}/status`) {
      return route.fulfill({ json: repoStatus });
    }
    if (path === `/repos/${REPO_ID}/runs`) {
      return route.fulfill({ json: runsResponse });
    }

    // Overview.
    if (path === `/repos/${REPO_ID}/passport`) {
      return route.fulfill({ json: passportResponse });
    }
    if (path === `/repos/${REPO_ID}/health`) {
      return route.fulfill({ json: healthResponse });
    }
    if (path === `/repos/${REPO_ID}/truck-factor`) {
      return route.fulfill({
        json: {
          repo_id: REPO_ID,
          value: 2,
          removal_order: [],
          total_files_considered: 120,
          orphaned_file_count: 5,
          note: null,
          interpretation: "This measures the project's knowledge-distribution risk.",
        },
      });
    }
    if (path === `/repos/${REPO_ID}/entry-points`) {
      return route.fulfill({
        json: {
          repo_id: REPO_ID,
          entry_points: [
            { file_path: "src/app.py", kind: "web_server", evidence: "Referenced by package.json scripts.start.", confidence: 0.95, rank: 0 },
          ],
        },
      });
    }

    // Map.
    if (path === `/repos/${REPO_ID}/subsystems`) {
      return route.fulfill({ json: subsystemsResponse });
    }
    if (path === `/repos/${REPO_ID}/module-coupling`) {
      return route.fulfill({ json: moduleCouplingSubsystemResponse });
    }
    if (path === `/repos/${REPO_ID}/architecture`) {
      return route.fulfill({ json: architectureResponse });
    }
    if (path === `/repos/${REPO_ID}/coupling`) {
      return route.fulfill({ json: couplingResponse });
    }
    if (path === `/repos/${REPO_ID}/hidden-dependencies`) {
      return route.fulfill({ json: hiddenDependenciesResponse });
    }
    if (path === `/repos/${REPO_ID}/city`) {
      return route.fulfill({ status: 202, json: { stage: "onboarding", status: "running" } });
    }

    // Findings -- the ranked stream plus its four evidence sections.
    if (path === `/repos/${REPO_ID}/findings`) {
      return route.fulfill({ json: findingsResponse });
    }
    if (path === `/repos/${REPO_ID}/secrets`) {
      return route.fulfill({ json: secretsResponseEmpty });
    }
    if (path === `/repos/${REPO_ID}/vulnerabilities`) {
      return route.fulfill({ json: vulnerabilitiesResponseEmptyPrimary });
    }
    if (path === `/repos/${REPO_ID}/hygiene`) {
      return route.fulfill({ json: hygieneResponseEmpty });
    }
    if (path === `/repos/${REPO_ID}/test-gaps`) {
      return route.fulfill({ json: testGapsResponseEmpty });
    }

    // Risk.
    if (path === `/repos/${REPO_ID}/risk`) {
      return route.fulfill({ json: riskResponse });
    }

    return route.fulfill({ status: 404, json: { detail: `unmocked path: ${path}` } });
  });

  // --- Landing: a showcase card is visible, click straight into Overview. ---
  await page.goto("/");
  await expect(page.getByText("acme/widgets")).toBeVisible();
  await expect(page.getByText("500 commits · 5 subsystems · truck factor 2")).toBeVisible();
  await page.getByText("acme/widgets").click();

  await expect(page).toHaveURL(new RegExp(`/repos/${REPO_ID}/overview$`));
  await expect(page.getByRole("heading", { name: "acme/widgets", level: 1 })).toBeVisible();
  await expect(page.getByText("Onboarding difficulty")).toBeVisible();
  await expect(page.getByText("Team shape")).toBeVisible();

  // --- Overview -> Map. Opens at subsystem level (never file level). -------
  await page.getByRole("link", { name: "Map" }).click();
  await expect(page).toHaveURL(new RegExp(`/repos/${REPO_ID}/map$`));
  await expect(page.getByText("Subsystems")).toBeVisible();
  await expect(page.getByText("billing", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Click a subsystem to expand it into its files.")).toBeVisible();

  // Expand "billing" -- the side list doubles as an expand control.
  await page.getByRole("button", { name: /billing/ }).click();
  await expect(page.getByText("Expanded:")).toBeVisible();
  await expect(page.getByRole("button", { name: "collapse" })).toBeVisible();

  // Collapse it again -- back to the unexpanded prompt.
  await page.getByRole("button", { name: "collapse" }).click();
  await expect(page.getByText("Click a subsystem to expand it into its files.")).toBeVisible();

  // --- Map -> Findings. Expand a finding, follow its deep link into
  // Structure, forced to file granularity with "hidden only" applied. ------
  await page.getByRole("link", { name: "Findings" }).click();
  await expect(page).toHaveURL(new RegExp(`/repos/${REPO_ID}/findings$`));

  const findingTitle = "Hidden dependency: src/app.py <-> src/auth/login.py";
  await expect(page.getByText(findingTitle)).toBeVisible();
  // Collapsed by default -- the deep link only appears once expanded.
  await expect(page.getByRole("link", { name: "View in Coupling" })).toHaveCount(0);

  await page.getByText(findingTitle).click();
  const couplingDeepLink = page.getByRole("link", { name: "View in Coupling" });
  await expect(couplingDeepLink).toBeVisible();
  await couplingDeepLink.click();

  await expect(page).toHaveURL(new RegExp(`/repos/${REPO_ID}/structure\\?`));
  await expect(page.getByText(/hidden dependencies only/i)).toBeVisible();
  await expect(page.getByText("app.py ↔ login.py")).toBeVisible();
  await expect(page.getByText("hidden", { exact: true }).first()).toBeVisible();

  // --- Structure -> Risk. Expand a hotspot row and open its ScoreExplainer,
  // reading the real, live weights from GET /meta/formulas. -----------------
  await page.getByRole("link", { name: "Risk" }).click();
  await expect(page).toHaveURL(new RegExp(`/repos/${REPO_ID}/risk$`));
  await expect(page.getByText("Risk vs. confidence")).toBeVisible();
  await expect(page.getByText("src/billing/invoice.py")).toBeVisible();

  await page.getByText("src/billing/invoice.py").click();
  await expect(page.getByText("View blast radius →")).toBeVisible();

  await page.getByText("How this is calculated").click();
  await expect(
    page.getByText(
      "risk_score = 0.60 x norm(churn_weighted x complexity) + 0.25 x norm(max coupling_degree) + 0.15 x norm(commit_count)",
    ),
  ).toBeVisible();
});
