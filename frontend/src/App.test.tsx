import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "./App";

describe("project scaffold", () => {
  it("identifies the project and does not imply weather features are live", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "Neural Flow Dynamics" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Weather data and forecasting features are not implemented yet.",
    );
  });
});
