import { expect, test, type Route } from "@playwright/test";
import {
  REPO_ID,
  architectureResponse,
  blastRadiusResponse,
  cityResponse,
  contributorsResponse,
  couplingResponse,
  entryPointsResponse,
  expertiseResponse,
  hiddenDependenciesResponse,
  knowledgeMapResponse,
  moduleCouplingSubsystemResponse,
  passportResponse,
  repoOut,
  repoStatus,
  subsystemsResponse,
  tourResponse,
  truckFactorResponse,
} from "./fixtures";

const API_URL = "http://localhost:8000";

// One Playwright test, not a suite (RULES.md sec 8 / Part H): "the Onboard
// product works" end to end against a mocked API -- Onboard -> passport ->
// tour -> people -> map -> impact. Every backend call this flow can make is
// routed here explicitly; anything unmatched falls through to a 404 fixture
// rather than a real network call, so a missed mock fails loudly (a hung/
// failed request) instead of silently hitting localhost:8000. Session 09
// extends this SAME test (not a new spec file) with the map's
// expand/collapse interaction and the impact explorer's file-select flow,
// per that session's own "extend the single existing test" instruction.
test("Onboard mode: passport -> tour -> people -> map -> impact", async ({ page }) => {
  await page.route(`${API_URL}/**`, (route: Route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;

    if (path === "/auth/me") {
      return route.fulfill({ status: 401, json: { detail: "Not authenticated" } });
    }
    if (path === `/repos/${REPO_ID}`) {
      return route.fulfill({ json: repoOut });
    }
    if (path === `/repos/${REPO_ID}/status`) {
      return route.fulfill({ json: repoStatus });
    }
    if (path === `/repos/${REPO_ID}/passport`) {
      return route.fulfill({ json: passportResponse });
    }
    if (path === `/repos/${REPO_ID}/truck-factor`) {
      return route.fulfill({ json: truckFactorResponse });
    }
    if (path === `/repos/${REPO_ID}/entry-points`) {
      return route.fulfill({ json: entryPointsResponse });
    }
    if (path === `/repos/${REPO_ID}/tour`) {
      return route.fulfill({ json: tourResponse });
    }
    if (path === `/repos/${REPO_ID}/knowledge-map`) {
      return route.fulfill({ json: knowledgeMapResponse });
    }
    if (path === `/repos/${REPO_ID}/contributors`) {
      return route.fulfill({ json: contributorsResponse });
    }
    if (path === `/repos/${REPO_ID}/expertise`) {
      expect(url.searchParams.get("path")).toBe("src/app.py");
      return route.fulfill({ json: expertiseResponse });
    }
    // Session 09: codebase map + impact explorer.
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
      return route.fulfill({ json: cityResponse });
    }
    if (path === `/repos/${REPO_ID}/blast-radius`) {
      expect(url.searchParams.get("path")).toBe("src/app.py");
      return route.fulfill({ json: blastRadiusResponse });
    }

    return route.fulfill({ status: 404, json: { detail: `unmocked path: ${path}` } });
  });

  await page.goto(`/repos/${REPO_ID}`);

  // Index redirect lands on Onboard's default tab (a fresh browser context
  // has no stored mode preference).
  await expect(page).toHaveURL(new RegExp(`/repos/${REPO_ID}/onboard/passport$`));
  await expect(page.getByRole("heading", { name: "acme/widgets", level: 1 })).toBeVisible();
  await expect(page.getByText("Onboarding difficulty")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Team shape" })).toBeVisible();

  // Passport -> Tour.
  await page.getByRole("link", { name: "Tour" }).click();
  await expect(page).toHaveURL(new RegExp(`/repos/${REPO_ID}/onboard/tour$`));
  await expect(page.getByText("Why this order")).toBeVisible();
  await expect(page.getByText("src/app.py")).toBeVisible();

  // Tour -> People.
  await page.getByRole("link", { name: "People" }).click();
  await expect(page).toHaveURL(new RegExp(`/repos/${REPO_ID}/onboard/people$`));
  await expect(page.getByText("Who do I ask?")).toBeVisible();

  // The flagship search: type into the file picker and select a match.
  const search = page.getByPlaceholder("Search files by path…");
  await search.click();
  await search.fill("app.py");
  await page.getByRole("button", { name: "src/app.py" }).click();

  // Its expert shows up, DOA and change count included, no email anywhere.
  await expect(page.getByText("Jane Doe").first()).toBeVisible();
  await expect(page.getByText("DOA 92%")).toBeVisible();
  await expect(page.getByText("40 changes")).toBeVisible();
  await expect(page.getByText("@example.com")).toHaveCount(0);

  // People -> Map. Opens at subsystem level (never file level) -- the
  // "Subsystems" side list is DOM, unlike the force-graph canvas itself, so
  // this is what the test can actually assert against.
  await page.getByRole("link", { name: "Map" }).click();
  await expect(page).toHaveURL(new RegExp(`/repos/${REPO_ID}/onboard/map$`));
  await expect(page.getByRole("heading", { name: "Subsystems" })).toBeVisible();
  await expect(page.getByText("billing", { exact: true })).toBeVisible();
  await expect(page.getByText("Click a subsystem to expand it into its files.")).toBeVisible();

  // Expand "billing" -- the side list doubles as an expand control.
  await page.getByRole("button", { name: /billing/ }).click();
  await expect(page.getByText("Expanded:")).toBeVisible();
  await expect(page.getByRole("button", { name: "collapse" })).toBeVisible();

  // Collapse it again -- back to the unexpanded prompt.
  await page.getByRole("button", { name: "collapse" }).click();
  await expect(page.getByText("Click a subsystem to expand it into its files.")).toBeVisible();

  // Map -> Impact. Pick a file, see its blast radius -- "coupled but NOT
  // imported" is the flagship result and must be visible, first.
  await page.getByRole("link", { name: "Impact" }).click();
  await expect(page).toHaveURL(new RegExp(`/repos/${REPO_ID}/onboard/impact$`));
  const impactSearch = page.getByPlaceholder("Search files by path…");
  await impactSearch.click();
  await impactSearch.fill("app.py");
  await page.getByRole("button", { name: "src/app.py" }).click();

  await expect(page.getByRole("heading", { name: "Coupled but NOT imported" })).toBeVisible();
  await expect(page.getByText("Files affected")).toBeVisible();
  // surprising_affected is a subset of historical_affected by definition
  // (coupled AND not structurally imported), so this text legitimately
  // appears more than once on the page -- .first() is the correct
  // assertion, not a workaround.
  await expect(page.getByText("src/auth/login.py").first()).toBeVisible();
});
