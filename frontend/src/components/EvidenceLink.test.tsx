import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { buildCommitUrl, EvidenceLink } from "./EvidenceLink";

const SHA = "abc1234def5678";

describe("buildCommitUrl", () => {
  it("builds a plain commit URL", () => {
    expect(buildCommitUrl("https://github.com/acme/widgets", SHA)).toBe(
      "https://github.com/acme/widgets/commit/abc1234def5678",
    );
  });

  it("strips a trailing slash", () => {
    expect(buildCommitUrl("https://github.com/acme/widgets/", SHA)).toBe(
      "https://github.com/acme/widgets/commit/abc1234def5678",
    );
  });

  it("strips multiple trailing slashes", () => {
    expect(buildCommitUrl("https://github.com/acme/widgets///", SHA)).toBe(
      "https://github.com/acme/widgets/commit/abc1234def5678",
    );
  });

  it("strips a .git suffix", () => {
    expect(buildCommitUrl("https://github.com/acme/widgets.git", SHA)).toBe(
      "https://github.com/acme/widgets/commit/abc1234def5678",
    );
  });

  it("strips a .git suffix combined with a trailing slash", () => {
    expect(buildCommitUrl("https://github.com/acme/widgets.git/", SHA)).toBe(
      "https://github.com/acme/widgets/commit/abc1234def5678",
    );
  });
});

describe("EvidenceLink", () => {
  it("renders a link to the correct commit URL, shortening the sha for display", () => {
    render(<EvidenceLink repoUrl="https://github.com/acme/widgets.git" sha={SHA} />);
    const link = screen.getByRole("link", { name: SHA.slice(0, 7) }) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("https://github.com/acme/widgets/commit/abc1234def5678");
    expect(link.target).toBe("_blank");
  });
});
