import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FilePicker } from "./FilePicker";

const PATHS = [
  "src/billing/invoice.py",
  "src/billing/ledger.py",
  "src/shipping/tracker.py",
  "README.md",
];

describe("FilePicker", () => {
  it("handles an empty path list without crashing, and disables the input", () => {
    render(<FilePicker paths={[]} onSelect={vi.fn()} />);
    expect(screen.getByText(/no files available yet/i)).toBeTruthy();
    const input = screen.getByRole("textbox") as HTMLInputElement;
    expect(input.disabled).toBe(true);
  });

  it("filters suggestions by substring match as the user types", () => {
    render(<FilePicker paths={PATHS} onSelect={vi.fn()} />);
    const input = screen.getByRole("textbox");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "billing" } });

    expect(screen.getByText("src/billing/invoice.py")).toBeTruthy();
    expect(screen.getByText("src/billing/ledger.py")).toBeTruthy();
    expect(screen.queryByText("src/shipping/tracker.py")).toBeNull();
    expect(screen.queryByText("README.md")).toBeNull();
  });

  it("is case-insensitive", () => {
    render(<FilePicker paths={PATHS} onSelect={vi.fn()} />);
    const input = screen.getByRole("textbox");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "README" } });
    expect(screen.getByText("README.md")).toBeTruthy();
  });

  it("calls onSelect with the chosen path and closes the dropdown", () => {
    const onSelect = vi.fn();
    render(<FilePicker paths={PATHS} onSelect={onSelect} />);
    const input = screen.getByRole("textbox");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "ledger" } });

    fireEvent.click(screen.getByText("src/billing/ledger.py"));

    expect(onSelect).toHaveBeenCalledWith("src/billing/ledger.py");
  });

  it("shows nothing selectable when the query matches no path", () => {
    render(<FilePicker paths={PATHS} onSelect={vi.fn()} />);
    const input = screen.getByRole("textbox");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "nonexistent-file-xyz" } });
    expect(screen.queryAllByRole("listitem").length).toBe(0);
  });
});
