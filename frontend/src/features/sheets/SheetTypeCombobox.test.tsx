import { I18nProvider } from "@lingui/react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import type { components } from "../../api/schema.gen";
import { i18n, initI18n } from "../../i18n";
import { SHEET_TYPE } from "../test-api";
import { matchSheetType } from "./matchSheetType";
import { SheetTypeCombobox } from "./SheetTypeCombobox";

type Type = components["schemas"]["SheetTypeRead"];

const geometry = (w: number, h: number) => ({ ...SHEET_TYPE.geometry, label_w: w, label_h: h });
const L4736: Type = { ...SHEET_TYPE, geometry: geometry(45.7, 21.2) };
const AVERY: Type = {
  ...SHEET_TYPE,
  key: "avery-5159",
  vendor: "Avery",
  product_codes: ["5159", "8160"],
  description: "30 address labels, Café edition",
  geometry: geometry(101.6, 38.1),
};
const PLAIN: Type = { ...SHEET_TYPE, key: "my-small", vendor: null, product_codes: [], description: null, geometry: geometry(20, 10) };
const ARCHIVED: Type = { ...SHEET_TYPE, key: "old-one", vendor: "Herma", product_codes: ["4400"], archived_at: "2026-01-01T00:00:00Z" };
const TYPES = [L4736, AVERY, PLAIN, ARCHIVED];

beforeAll(() => initI18n("en"));

describe("matchSheetType", () => {
  it("an empty query matches everything", () => {
    expect(matchSheetType(AVERY, "")).toBe(true);
    expect(matchSheetType(AVERY, "   ")).toBe(true);
  });

  it("matches by key, vendor, product code and description", () => {
    expect(matchSheetType(L4736, "4736")).toBe(true);
    expect(matchSheetType(AVERY, "avery-51")).toBe(true);
    expect(matchSheetType(AVERY, "AVERY")).toBe(true);
    expect(matchSheetType(AVERY, "8160")).toBe(true);
    expect(matchSheetType(AVERY, "address labels")).toBe(true);
  });

  it("is accent-insensitive in both directions", () => {
    expect(matchSheetType(AVERY, "cafe")).toBe(true);
    expect(matchSheetType(AVERY, "café")).toBe(true);
    expect(matchSheetType({ ...AVERY, description: "Etikett Ünïcode" }, "unicode")).toBe(true);
  });

  it.each(["101,6 × 38,1", "101.6x38.1", "101,6x38,1", "101,6 x 38.1", "101,6×38,1"])("matches the size written as %s", (query) => {
    expect(matchSheetType(AVERY, query)).toBe(true);
    expect(matchSheetType(L4736, query)).toBe(false);
  });

  it("matches one side of the size on its own", () => {
    expect(matchSheetType(AVERY, "101,6")).toBe(true);
    expect(matchSheetType(AVERY, "38.1")).toBe(true);
  });

  it("every word of the query has to match", () => {
    expect(matchSheetType(AVERY, "avery 5159")).toBe(true);
    expect(matchSheetType(AVERY, "avery 4736")).toBe(false);
  });

  it("matches no unrelated query", () => {
    expect(matchSheetType(AVERY, "zebra")).toBe(false);
    expect(matchSheetType(PLAIN, "avery")).toBe(false);
  });

  it("copes with a type that has no vendor, codes or description", () => {
    expect(matchSheetType(PLAIN, "my-small")).toBe(true);
    expect(matchSheetType(PLAIN, "20x10")).toBe(true);
  });
});

function Harness({ initial = "L4736REV", onChange = () => {}, noneOption }: { initial?: string; onChange?: (id: string) => void; noneOption?: { id: string; label: string } }) {
  const [value, setValue] = useState(initial);
  return (
    <I18nProvider i18n={i18n}>
      <SheetTypeCombobox
        label="Sheet type"
        types={TYPES}
        value={value}
        noneOption={noneOption}
        onChange={(id) => {
          setValue(id);
          onChange(id);
        }}
      />
    </I18nProvider>
  );
}

const box = () => screen.getByRole("combobox", { name: "Sheet type" });

describe("SheetTypeCombobox", () => {
  it("shows the chosen type in the label format", () => {
    render(<Harness />);
    expect(box()).toHaveValue("Example Labels L4736REV-25 (L4736REV) · 45.7 × 21.2 mm");
  });

  it("keyboard selects a type", async () => {
    const onChange = vi.fn();
    render(<Harness initial="my-small" onChange={onChange} />);
    await userEvent.click(box());
    await userEvent.keyboard("4736");
    const list = await screen.findByRole("listbox");
    expect(within(list).getAllByRole("option")).toHaveLength(1);
    await userEvent.keyboard("{ArrowDown}{Enter}");
    expect(onChange).toHaveBeenCalledWith("L4736REV");
  });

  it("a click starts a new search: typing replaces the shown label instead of appending to it", async () => {
    render(<Harness initial="avery-5159" />);
    await userEvent.click(box());
    await userEvent.keyboard("4736");
    expect(box()).toHaveValue("4736");
    expect(within(await screen.findByRole("listbox")).getAllByRole("option")).toHaveLength(1);
  });

  it("selects the whole label on tap", async () => {
    const spy = vi.spyOn(HTMLInputElement.prototype, "setSelectionRange");
    try {
      render(<Harness initial="avery-5159" />);
      await userEvent.click(box());
      const input = box() as HTMLInputElement;
      // An explicit range, not only select(): some mobile browsers drop the latter.
      expect(spy).toHaveBeenCalledWith(0, input.value.length);
      expect(input.value.length).toBeGreaterThan(0);
    } finally {
      spy.mockRestore();
    }
  });

  it("keeps the first character typed after a selection", () => {
    // The deferred re-select (setTimeout 0, for iOS) is still pending when the first keystroke arrives. RTL drains a
    // macrotask after each user-event call, which hides this window, so the events here are synchronous and the timers fake.
    vi.useFakeTimers();
    try {
      render(<Harness initial="avery-5159" />);
      const input = box() as HTMLInputElement;
      act(() => input.focus());
      // The label is selected; typing one character replaces it.
      fireEvent.change(input, { target: { value: "4" } });
      expect(input).toHaveValue("4");
      act(() => {
        vi.advanceTimersByTime(0);
      });
      // A re-select now would put the typed character under the selection: the next keystroke would replace it.
      expect(input).toHaveValue("4");
      expect(input.selectionStart).toBe(input.selectionEnd);
    } finally {
      vi.useRealTimers();
    }
  });

  it("ArrowDown to an option and Tab chooses it", async () => {
    // react-aria's Tab handler commits the option that has the virtual focus, like Enter does.
    const onChange = vi.fn();
    render(<Harness initial="my-small" onChange={onChange} />);
    await userEvent.click(box());
    await userEvent.keyboard("avery");
    await screen.findByRole("listbox");
    await userEvent.keyboard("{ArrowDown}{Tab}");
    expect(onChange).toHaveBeenCalledWith("avery-5159");
  });

  it("a selection that nobody pressed, or chose with Enter or Tab on an option, is not a pick", async () => {
    // react-aria commits the chosen key on its own (useComboBoxState commitValue -> onSelectionChange(selectedKey)), e.g.
    // when a scroll closes the list; that must not be taken as a choice (it wipes the search).
    const onChange = vi.fn();
    render(<Harness initial="L4736REV" onChange={onChange} />);
    await userEvent.click(box());
    await userEvent.keyboard("4736"); // matches the chosen type itself, so its text is still in the list
    expect(await screen.findByRole("listbox")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}"); // react-aria reverts: commitSelection -> onSelectionChange(selectedKey)
    expect(onChange).not.toHaveBeenCalled();
  });

  it("a press on an option that never ends (a touch that turns into a scroll) is not a choice", async () => {
    const onChange = vi.fn();
    render(<Harness initial="L4736REV" onChange={onChange} />);
    await userEvent.click(box());
    await userEvent.keyboard("4736");
    const option = await screen.findByRole("option", { name: /L4736REV/ });
    fireEvent.pointerDown(option);
    fireEvent.pointerCancel(option); // the finger moved: it is a scroll, there is no pointer-up
    await userEvent.keyboard("{Escape}"); // react-aria reverts and commits the chosen key
    expect(onChange).not.toHaveBeenCalled();
  });

  it("a tap on the field that already has the focus opens the list again", async () => {
    render(<Harness />);
    await userEvent.click(box());
    await userEvent.keyboard("{ArrowDown}{Enter}"); // chooses; the list closes, the focus stays
    await waitFor(() => expect(screen.queryByRole("listbox")).toBeNull());
    await userEvent.click(box());
    expect(await screen.findByRole("listbox")).toBeInTheDocument();
    await userEvent.keyboard("4736"); // and it is a new search again, not text added to the label
    expect(box()).toHaveValue("4736");
  });

  it.each([
    ["38,1", "38.1"],
    ["45.7x21.2", "45.7 × 21.2"],
    ["45,7 × 21,2", "45.7 × 21.2"],
  ])("marks the match where it is, also after the size: %s", async (query, marked) => {
    render(<Harness />);
    await userEvent.click(box());
    await userEvent.keyboard(query);
    const option = (await screen.findAllByRole("option")).find((o) => o.querySelector("mark"));
    expect(option?.querySelector("mark")?.textContent).toBe(marked);
  });

  it("Enter on a search takes the first match", async () => {
    const onChange = vi.fn();
    render(<Harness initial="my-small" onChange={onChange} />);
    await userEvent.click(box());
    await userEvent.keyboard("avery{Enter}");
    expect(onChange).toHaveBeenCalledWith("avery-5159");
  });

  it("escape restores previous value", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const before = (box() as HTMLInputElement).value;
    await userEvent.click(box());
    await userEvent.keyboard("zzz");
    expect(box()).toHaveValue("zzz");
    await userEvent.keyboard("{Escape}");
    expect(box()).toHaveValue(before);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("filters accent-insensitively and says when nothing matches", async () => {
    render(<Harness />);
    await userEvent.click(box());
    await userEvent.keyboard("cafe");
    expect(within(await screen.findByRole("listbox")).getAllByRole("option")).toHaveLength(1);
    await userEvent.keyboard("-nothing-like-this");
    expect(await screen.findByText("No sheet type matches.")).toBeInTheDocument();
  });

  it("Home and End jump to the first and the last option", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await userEvent.click(box());
    await screen.findByRole("listbox");
    await userEvent.keyboard("{ArrowDown}{End}{Enter}");
    expect(onChange).toHaveBeenLastCalledWith("old-one");
    await userEvent.keyboard("{ArrowDown}"); // the field still has the focus; ArrowDown opens the list again
    await screen.findByRole("listbox");
    await userEvent.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}{Home}{Enter}");
    expect(onChange).toHaveBeenLastCalledWith("L4736REV");
  });

  // The 16 px input and the 44 px options are measured in a real browser: e2e/calibration.spec.ts (jsdom has no layout).

  it("the none option is the placeholder, never text in the field, and still listed", async () => {
    const onChange = vi.fn();
    render(<Harness initial="none" noneOption={{ id: "none", label: "Choose a sheet type" }} onChange={onChange} />);
    expect(box()).toHaveValue("");
    expect(box()).toHaveAttribute("placeholder", "Choose a sheet type");
    await userEvent.click(box());
    expect(await screen.findByRole("option", { name: "Choose a sheet type" })).toBeInTheDocument();
  });

  it("offers the clear button", async () => {
    const onChange = vi.fn();
    render(<Harness initial="none" noneOption={{ id: "none", label: "Choose a sheet type" }} onChange={onChange} />);
    await userEvent.click(box());
    await userEvent.keyboard("avery");
    await userEvent.click(screen.getByRole("button", { name: "Clear the search", hidden: true }) /* React Aria hides everything but the list while it is open */);
    expect(box()).toHaveValue("");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("select shows full text on touch", () => {
    const long: Type = { ...AVERY, key: "avery-zweckform-l4736rev", vendor: "Avery Zweckform", product_codes: ["L4736REV"] };
    render(
      <I18nProvider i18n={i18n}>
        <SheetTypeCombobox label="Sheet type" types={[long]} value={long.key} onChange={() => {}} />
      </I18nProvider>,
    );
    // The text below the field is the whole label, product code included; it is hidden for a mouse by CSS, not left out of the page.
    const full = document.querySelector("[data-full-label]");
    expect(full).not.toBeNull();
    expect(full!.textContent).toBe(box().getAttribute("title"));
    expect(full!.textContent).toContain("Avery Zweckform L4736REV");
    expect(full!.className).toContain("[@media(hover:hover)_and_(pointer:fine)]:hidden");
  });

  it("writes no full text below the field for the none option", () => {
    render(<Harness initial="__any__" noneOption={{ id: "__any__", label: "Any sheet type" }} />);
    expect(document.querySelector("[data-full-label]")).toBeNull();
  });

  it("shows a 64-character key and a long vendor on one line with the full text in the title", async () => {
    const longKey = "k".repeat(64);
    const long: Type = { ...AVERY, key: longKey, vendor: "A Very Long Vendor Name Holdings International" };
    render(
      <I18nProvider i18n={i18n}>
        <SheetTypeCombobox label="Sheet type" types={[long]} value={longKey} onChange={() => {}} />
      </I18nProvider>,
    );
    expect(box()).toHaveAttribute("title", expect.stringContaining(longKey));
  });
});
