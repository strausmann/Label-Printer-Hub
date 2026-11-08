import { render as rtlRender, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { I18nProvider } from "@lingui/react";
import type { ReactElement } from "react";
import { i18n, initI18n } from "../../i18n";
import type { GeometryMm } from "./cellState";
import { GeometryDiagram } from "./GeometryDiagram";

const G: GeometryMm = {
  page_size: "A4", page_w: 210, page_h: 297, label_w: 45.7, label_h: 21.2, cols: 4, rows: 12,
  pitch_x: 48.2, pitch_y: 21.2, margin_top: 21.3, margin_left: 9.85, corner_radius: null, shape: "rectangle",
};

const render = (ui: ReactElement) =>
  rtlRender(ui, { wrapper: ({ children }) => <I18nProvider i18n={i18n}>{children}</I18nProvider> });

beforeEach(async () => {
  await initI18n("en");
});

describe("GeometryDiagram", () => {
  it("shows an unknown corner radius as the word", () => {
    render(<GeometryDiagram geometry={G} />);
    expect(screen.getByText("Corner radius").nextElementSibling).toHaveTextContent("unknown");
  });

  it("shows a known radius, and gaps and computed margins", () => {
    render(<GeometryDiagram geometry={{ ...G, corner_radius: 1.5 }} />);
    expect(screen.getByText("Corner radius").nextElementSibling).toHaveTextContent("1.5 mm");
    expect(screen.getByText("Gap between columns").nextElementSibling).toHaveTextContent("2.5 mm");
    expect(screen.getByText("Gap between rows").nextElementSibling).toHaveTextContent("0 mm");
    // right = 210 - (9.85 + 3 * 48.2 + 45.7) = 9.85 ; bottom = 297 - (21.3 + 11 * 21.2 + 21.2) = 21.3
    expect(screen.getByText("Right margin").nextElementSibling).toHaveTextContent("9.85 mm");
    expect(screen.getByText("Bottom margin").nextElementSibling).toHaveTextContent("21.3 mm");
  });

  it("flags asymmetric margins on its own when no hints are given", () => {
    render(<GeometryDiagram geometry={{ ...G, margin_left: 4 }} />);
    expect(screen.getByRole("note")).toHaveTextContent(/left and right margins differ/i);
  });

  it("uses the server's hints when given, and stays quiet for none", () => {
    const { rerender } = render(<GeometryDiagram geometry={{ ...G, margin_left: 4 }} hints={[]} />);
    expect(screen.queryByRole("note")).toBeNull();
    rerender(<GeometryDiagram geometry={G} hints={["margins_asymmetric_y"]} />);
    expect(within(screen.getByRole("note")).getByText(/top and bottom margins differ/i)).toBeVisible();
  });

  it("says a round sheet has no corner radius to measure", () => {
    render(<GeometryDiagram geometry={{ ...G, shape: "round", label_h: 45.7, pitch_y: 48 }} />);
    expect(screen.getByText("Corner radius").nextElementSibling).toHaveTextContent("round");
  });

  it("survives a geometry without page dimensions", () => {
    render(<GeometryDiagram geometry={{ ...G, page_w: null, page_h: null }} />);
    expect(screen.getByText("Right margin").nextElementSibling).not.toHaveTextContent("NaN");
  });
});
