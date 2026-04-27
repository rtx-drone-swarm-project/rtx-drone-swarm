import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import LegendPanel from "./LegendPanel";

describe("LegendPanel", () => {
  it("renders the current operational marker states", () => {
    render(<LegendPanel />);

    expect(screen.getByText("Drone")).toBeTruthy();
    expect(screen.getByText("Finder drone")).toBeTruthy();
    expect(screen.getByText("Confirmer drone")).toBeTruthy();
    expect(screen.getByText("Hiker detected / wandering target")).toBeTruthy();
    expect(screen.getByText("Hiker being confirmed")).toBeTruthy();
    expect(screen.getByText("Hiker found")).toBeTruthy();
    expect(screen.getByText("Search area boundary")).toBeTruthy();
    expect(screen.getByText(/Drone call signs appear on hover/i)).toBeTruthy();
    expect(screen.getByText(/Blue marks finder drones, orange marks confirmers/i)).toBeTruthy();
  });
});
