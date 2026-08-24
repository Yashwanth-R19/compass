import { expect, test, type Route } from "@playwright/test";
import {
  REPO_ID,
  contributorsResponse,
  entryPointsResponse,
  expertiseResponse,
  knowledgeMapResponse,
  passportResponse,
  repoOut,
  repoStatus,
  tourResponse,
  truckFactorResponse,
} from "./fixtures";

const API_URL = "http://localhost:8000";

// One Playwright test, not a suite (RULES.md sec 8 / Part H): "the Onboard
// product works" end to end against a mocked API -- Onboard -> passport ->
// tour -> people, pick a file in the picker, see its experts. Every backend
// call this flow can make is routed here explicitly; anything unmatched
// falls through to a 404 fixture rather than a real network call, so a
// missed mock fails loudly (a hung/failed request) instead of silently
// hitting localhost:8000.
test("Onboard mode: passport -> tour -> people, and the file picker finds experts", async ({
  page,
}) => {
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
});
