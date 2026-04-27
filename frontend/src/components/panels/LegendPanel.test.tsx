import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import LegendPanel from "./LegendPanel";

describe("LegendPanel", () => {
  it("renders all marker symbol rows", () => {
    render(<LegendPanel />);

    expect(screen.getByText("Drone")).toBeTruthy();
    expect(screen.getByText("Finder drone")).toBeTruthy();
    expect(screen.getByText("Confirmer drone")).toBeTruthy();
    expect(screen.getByText("Hiker detected / wandering target")).toBeTruthy();
    expect(screen.getByText("Hiker being confirmed")).toBeTruthy();
    expect(screen.getByText("Hiker found")).toBeTruthy();
    expect(screen.getByText("Search area boundary")).toBeTruthy();
  });

  it("renders the compact how-to hint and not the old verbose note", () => {
    render(<LegendPanel />);

    expect(screen.getByText(/Drag to draw area/i)).toBeTruthy();
    expect(screen.getByText(/Scroll to zoom/i)).toBeTruthy();
    expect(screen.getByText(/Click drone for details/i)).toBeTruthy();

    expect(screen.queryByText(/Drone call signs appear on hover/i)).toBeNull();
    expect(screen.queryByText(/Blue marks finder drones/i)).toBeNull();
  });
});
