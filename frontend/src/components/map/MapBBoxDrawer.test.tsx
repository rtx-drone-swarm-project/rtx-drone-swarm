import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MapBBoxDrawer from "./MapBBoxDrawer";

type MockLeafletEvent = {
  latlng: {
    lat: number;
    lng: number;
  };
  originalEvent?: {
    shiftKey?: boolean;
  };
};

let eventHandlers: Record<string, ((event: MockLeafletEvent) => void) | undefined> = {};

const dragging = {
  disable: vi.fn(),
  enable: vi.fn()
};

const container = {
  style: {
    cursor: ""
  }
};

const map = {
  dragging,
  getContainer: () => container
};

vi.mock("react-leaflet", () => ({
  Rectangle: () => <div data-testid="preview-rectangle" />,
  useMap: () => map,
  useMapEvents: (handlers: Record<string, (event: MockLeafletEvent) => void>) => {
    eventHandlers = handlers;
    return null;
  }
}));

beforeEach(() => {
  eventHandlers = {};
  container.style.cursor = "";
  dragging.disable.mockClear();
  dragging.enable.mockClear();
});

describe("MapBBoxDrawer", () => {
  it("does not start drawing on plain drag", () => {
    const onBoundsDrawn = vi.fn();
    render(<MapBBoxDrawer enabled={true} onBoundsDrawn={onBoundsDrawn} />);

    act(() => {
      eventHandlers.mousedown?.({ latlng: { lat: 33.5, lng: -117.2 }, originalEvent: { shiftKey: false } });
      eventHandlers.mousemove?.({ latlng: { lat: 33.6, lng: -117.1 } });
      eventHandlers.mouseup?.({ latlng: { lat: 33.6, lng: -117.1 } });
    });

    expect(screen.queryByTestId("preview-rectangle")).toBeNull();
    expect(dragging.disable).not.toHaveBeenCalled();
    expect(dragging.enable).not.toHaveBeenCalled();
    expect(onBoundsDrawn).not.toHaveBeenCalled();
  });

  it("draws a preview and emits bounds on shift-drag", () => {
    const onBoundsDrawn = vi.fn();
    render(<MapBBoxDrawer enabled={true} onBoundsDrawn={onBoundsDrawn} />);

    act(() => {
      eventHandlers.mousedown?.({ latlng: { lat: 33.5, lng: -117.2 }, originalEvent: { shiftKey: true } });
    });

    expect(dragging.disable).toHaveBeenCalledTimes(1);
    expect(container.style.cursor).toBe("crosshair");

    act(() => {
      eventHandlers.mousemove?.({ latlng: { lat: 33.55, lng: -117.15 } });
    });

    expect(screen.getByTestId("preview-rectangle")).toBeTruthy();

    act(() => {
      eventHandlers.mouseup?.({ latlng: { lat: 33.55, lng: -117.15 } });
    });

    expect(dragging.enable).toHaveBeenCalledTimes(1);
    expect(container.style.cursor).toBe("");
    expect(onBoundsDrawn).toHaveBeenCalledWith({
      min_lat: 33.5,
      max_lat: 33.55,
      min_lon: -117.2,
      max_lon: -117.15
    });
  });

  it("emits the same normalized bounds when dragged in reverse", () => {
    const onBoundsDrawn = vi.fn();
    render(<MapBBoxDrawer enabled={true} onBoundsDrawn={onBoundsDrawn} />);

    act(() => {
      eventHandlers.mousedown?.({ latlng: { lat: 33.55, lng: -117.15 }, originalEvent: { shiftKey: true } });
    });

    act(() => {
      eventHandlers.mousemove?.({ latlng: { lat: 33.5, lng: -117.2 } });
    });

    act(() => {
      eventHandlers.mouseup?.({ latlng: { lat: 33.5, lng: -117.2 } });
    });

    expect(onBoundsDrawn).toHaveBeenCalledWith({
      min_lat: 33.5,
      max_lat: 33.55,
      min_lon: -117.2,
      max_lon: -117.15
    });
  });

  it("does not emit bounds for a tiny shift-drag", () => {
    const onBoundsDrawn = vi.fn();
    render(<MapBBoxDrawer enabled={true} onBoundsDrawn={onBoundsDrawn} />);

    act(() => {
      eventHandlers.mousedown?.({ latlng: { lat: 33.5, lng: -117.2 }, originalEvent: { shiftKey: true } });
    });

    act(() => {
      eventHandlers.mousemove?.({ latlng: { lat: 33.5004, lng: -117.1997 } });
    });

    act(() => {
      eventHandlers.mouseup?.({ latlng: { lat: 33.5004, lng: -117.1997 } });
    });

    expect(dragging.disable).toHaveBeenCalledTimes(1);
    expect(dragging.enable).toHaveBeenCalledTimes(1);
    expect(onBoundsDrawn).not.toHaveBeenCalled();
  });

  it("restores dragging and cursor on unmount during an active draw", () => {
    const onBoundsDrawn = vi.fn();
    const view = render(<MapBBoxDrawer enabled={true} onBoundsDrawn={onBoundsDrawn} />);

    act(() => {
      eventHandlers.mousedown?.({ latlng: { lat: 33.5, lng: -117.2 }, originalEvent: { shiftKey: true } });
    });

    expect(container.style.cursor).toBe("crosshair");

    view.unmount();

    expect(dragging.enable).toHaveBeenCalledTimes(1);
    expect(container.style.cursor).toBe("");
    expect(onBoundsDrawn).not.toHaveBeenCalled();
  });
});
