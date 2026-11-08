import { fireEvent, render as rtlRender, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "@lingui/react";
import type { ReactElement } from "react";
import { i18n, initI18n } from "../../i18n";
import type { GeometryMm, GridCell, GridCellState } from "./cellState";
import { SheetGrid, SheetLegend } from "./SheetGrid";

const L4736: GeometryMm = {
  page_size: "A4", page_w: 210, page_h: 297, label_w: 45.7, label_h: 21.2, cols: 4, rows: 12,
  pitch_x: 48.2, pitch_y: 21.2, margin_top: 21.3, margin_left: 9.85, corner_radius: null, shape: "rectangle",
};
const L4731: GeometryMm = {
  page_size: "A4", page_w: 210, page_h: 297, label_w: 25.4, label_h: 10, cols: 7, rows: 27,
  pitch_x: 27.9, pitch_y: 10, margin_top: 13.5, margin_left: 8.6, corner_radius: 1.5, shape: "rectangle",
};
const ROUND: GeometryMm = {
  page_size: "A4", page_w: 210, page_h: 297, label_w: 30, label_h: 30, cols: 5, rows: 8,
  pitch_x: 36, pitch_y: 36, margin_top: 10, margin_left: 15, corner_radius: null, shape: "round",
};

const render = (ui: ReactElement) =>
  rtlRender(ui, { wrapper: ({ children }) => <I18nProvider i18n={i18n}>{children}</I18nProvider> });

beforeEach(async () => {
  await initI18n("en");
});

const mk = (n: number, state: GridCellState, extra: Partial<GridCell> = {}): GridCell => ({ cell: n, state, ...extra });
const cell = (n: number) => screen.getByRole("gridcell", { name: new RegExp(`^Cell ${n},`) });

describe("grid keyboard navigation and labels", () => {
  const cells = [mk(5, "used", { purpose: "Grocy · flour 1 kg" }), mk(6, "free")];

  it("is an ARIA grid whose cells are labelled like 'Cell 5, used, Grocy · flour 1 kg'", () => {
    render(<SheetGrid geometry={L4736} cells={cells} mode="view" label="Sheet L4736-0001" containerWidth={360} />);
    expect(screen.getByRole("grid", { name: "Sheet L4736-0001" })).toBeVisible();
    expect(screen.getAllByRole("row")).toHaveLength(12);
    expect(screen.getAllByRole("gridcell")).toHaveLength(48);
    expect(screen.getByRole("gridcell", { name: "Cell 5, used, Grocy · flour 1 kg" })).toBeInTheDocument();
    expect(cell(1)).toHaveAccessibleName("Cell 1, free"); // cells the data omits are free
  });

  it("arrow keys move by column and row and stay inside the grid", () => {
    render(<SheetGrid geometry={L4736} cells={cells} mode="view" label="g" containerWidth={360} />);
    cell(1).focus();
    expect(cell(1)).toHaveFocus();
    fireEvent.keyDown(cell(1), { key: "ArrowRight" });
    expect(cell(2)).toHaveFocus();
    fireEvent.keyDown(cell(2), { key: "ArrowDown" });
    expect(cell(6)).toHaveFocus();
    fireEvent.keyDown(cell(6), { key: "ArrowLeft" });
    expect(cell(5)).toHaveFocus();
    fireEvent.keyDown(cell(5), { key: "ArrowLeft" }); // row start: stays
    expect(cell(5)).toHaveFocus();
    fireEvent.keyDown(cell(5), { key: "ArrowUp" });
    expect(cell(1)).toHaveFocus();
    fireEvent.keyDown(cell(1), { key: "ArrowUp" }); // first row: stays
    expect(cell(1)).toHaveFocus();
    fireEvent.keyDown(cell(1), { key: "End" });
    expect(cell(4)).toHaveFocus();
    fireEvent.keyDown(cell(4), { key: "Home" });
    expect(cell(1)).toHaveFocus();
  });

  it("only one cell is in the tab order", () => {
    render(<SheetGrid geometry={L4736} cells={cells} mode="view" label="g" containerWidth={360} />);
    expect(screen.getAllByRole("gridcell").filter((c) => c.getAttribute("tabindex") === "0")).toHaveLength(1);
  });

  it("view mode never toggles", () => {
    const onToggle = vi.fn();
    render(<SheetGrid geometry={L4736} cells={cells} mode="view" onToggle={onToggle} label="g" containerWidth={360} />);
    fireEvent.click(cell(6));
    fireEvent.keyDown(cell(6), { key: " " });
    expect(onToggle).not.toHaveBeenCalled();
  });
});

describe("cell states are never colour alone", () => {
  it.each<[GridCellState, string]>([
    ["free", "free"], ["used", "hatch"], ["reserved", "clock"],
    ["unconfirmed", "question"], ["new", "filled"], ["skipped", "cross"],
  ])("%s carries the %s marker", (state, marker) => {
    render(<SheetGrid geometry={L4736} cells={[mk(1, state)]} mode="view" label="g" containerWidth={360} />);
    expect(cell(1).querySelector(`[data-marker="${marker}"]`)).not.toBeNull();
  });

  it("the legend names every state with its marker", () => {
    render(<SheetLegend counts={{ used: 120, free: 69 }} />);
    const list = screen.getByRole("list");
    expect(within(list).getAllByRole("listitem")).toHaveLength(6);
    expect(within(list).getByText("used").closest("li")).toHaveTextContent("120");
    expect(list.querySelectorAll("[data-marker]").length).toBeGreaterThanOrEqual(6);
  });
});

describe("shapes and markers", () => {
  it("round cells render circles", () => {
    const { container } = render(<SheetGrid geometry={ROUND} cells={[]} mode="view" label="g" containerWidth={360} />);
    expect(container.querySelectorAll('[data-shape="cell"]')).toHaveLength(40);
    expect(container.querySelectorAll('circle[data-shape="cell"]')).toHaveLength(40);
    expect(container.querySelectorAll('rect[data-shape="cell"]')).toHaveLength(0);
  });

  it("rectangular cells render rounded rects, also with an unknown radius", () => {
    const { container } = render(<SheetGrid geometry={L4736} cells={[]} mode="view" label="g" containerWidth={360} />);
    expect(container.querySelectorAll('rect[data-shape="cell"]')).toHaveLength(48);
  });

  it("marks the ID cell and a hardware-margin cell with an element", () => {
    const { container } = render(
      <SheetGrid geometry={L4736} cells={[mk(1, "new", { isId: true, hwMargin: true })]} mode="view" label="g" containerWidth={360} />,
    );
    expect(container.querySelector('[data-marker="id"]')).not.toBeNull();
    expect(container.querySelector('[data-marker="hw-margin"]')).not.toBeNull();
    expect(cell(1)).toHaveAccessibleName(/sheet ID.*unprintable margin/);
  });

  it("draws the overlay PNG across the whole page", () => {
    const { container } = render(
      <SheetGrid geometry={L4736} cells={[]} mode="view" overlayPng="data:image/png;base64,AAAA" label="g" containerWidth={360} />,
    );
    const img = container.querySelector("image");
    expect(img).toHaveAttribute("href", "data:image/png;base64,AAAA");
    expect(img).toHaveAttribute("width", "210");
    expect(img).toHaveAttribute("height", "297");
  });
});

describe("select and skip", () => {
  it("select mode toggles a free cell with click, Space and Enter", () => {
    const onToggle = vi.fn();
    render(<SheetGrid geometry={L4736} cells={[mk(5, "free")]} mode="select" onToggle={onToggle} label="g" containerWidth={800} />);
    fireEvent.click(cell(5));
    expect(onToggle).toHaveBeenLastCalledWith(5);
    fireEvent.keyDown(cell(5), { key: " " });
    fireEvent.keyDown(cell(5), { key: "Enter" });
    expect(onToggle).toHaveBeenCalledTimes(3);
  });

  it("select mode refuses used cells by default and marks them aria-disabled", () => {
    const onToggle = vi.fn();
    render(<SheetGrid geometry={L4736} cells={[mk(5, "used")]} mode="select" onToggle={onToggle} label="g" containerWidth={800} />);
    expect(cell(5)).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(cell(5));
    fireEvent.keyDown(cell(5), { key: "Enter" });
    expect(onToggle).not.toHaveBeenCalled();
  });

  it("skip mode offers cells planned as new by default", () => {
    const onToggle = vi.fn();
    render(
      <SheetGrid geometry={L4736} cells={[mk(2, "new"), mk(3, "free")]} mode="skip" onToggle={onToggle} label="g" containerWidth={800} />,
    );
    fireEvent.click(cell(3));
    expect(onToggle).not.toHaveBeenCalled();
    fireEvent.click(cell(2));
    expect(onToggle).toHaveBeenCalledWith(2);
  });

  it("a selectable predicate overrides the default (un-mark only hand-marked cells)", () => {
    const onToggle = vi.fn();
    const cells = [mk(1, "used", { mapped: true }), mk(2, "used")];
    render(
      <SheetGrid geometry={L4736} cells={cells} mode="select" onToggle={onToggle} selectable={(c) => c.state === "used" && !!c.mapped}
        label="g" containerWidth={800} />,
    );
    fireEvent.click(cell(2));
    expect(onToggle).not.toHaveBeenCalled();
    fireEvent.click(cell(1));
    expect(onToggle).toHaveBeenCalledWith(1);
  });
});

describe("sizing", () => {
  const svgOf = (c: HTMLElement) => c.querySelector("svg")!;

  it("view fits 360", () => {
    const { container } = render(<SheetGrid geometry={L4731} cells={[]} mode="view" label="g" containerWidth={360} />);
    const svg = svgOf(container);
    expect(Number(svg.getAttribute("width"))).toBeLessThanOrEqual(360);
    const scale = Number(svg.getAttribute("width")) / 210;
    expect(27.9 * scale).toBeGreaterThanOrEqual(44); // the pitch box is the touch target
  });

  it("tap view cells are 44 px", () => {
    const { container } = render(<SheetGrid geometry={L4731} cells={[]} mode="select" label="g" containerWidth={360} />);
    const svg = svgOf(container);
    const scale = Number(svg.getAttribute("width")) / 210;
    const hit = container.querySelector('[data-hit="1"]')!;
    expect(Number(hit.getAttribute("width")) * scale).toBeGreaterThanOrEqual(44 - 1e-6);
    expect(Number(hit.getAttribute("height")) * scale).toBeGreaterThanOrEqual(44 - 1e-6);
    // the scroll container, not the page, takes the overflow
    const scroller = container.querySelector('[data-scroll="both"]');
    expect(scroller).not.toBeNull();
    expect(Number(svg.getAttribute("width"))).toBeGreaterThan(360);
  });

  it("without ResizeObserver it falls back to a 360 px phone", () => {
    expect(globalThis.ResizeObserver).toBeUndefined();
    const { container } = render(<SheetGrid geometry={L4731} cells={[]} mode="view" label="g" />);
    expect(Number(svgOf(container).getAttribute("width"))).toBeLessThanOrEqual(360);
  });
});
