import { I18nProvider } from "@lingui/react";
import { render, screen, within } from "@testing-library/react";
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
    await userEvent.keyboard("{Control>}a{/Control}4736");
    const list = await screen.findByRole("listbox");
    expect(within(list).getAllByRole("option")).toHaveLength(1);
    await userEvent.keyboard("{ArrowDown}{Enter}");
    expect(onChange).toHaveBeenCalledWith("L4736REV");
  });

  it("Enter on a search takes the first match", async () => {
    const onChange = vi.fn();
    render(<Harness initial="my-small" onChange={onChange} />);
    await userEvent.click(box());
    await userEvent.keyboard("{Control>}a{/Control}avery{Enter}");
    expect(onChange).toHaveBeenCalledWith("avery-5159");
  });

  it("escape restores previous value", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const before = (box() as HTMLInputElement).value;
    await userEvent.click(box());
    await userEvent.keyboard("{Control>}a{/Control}zzz");
    expect(box()).toHaveValue("zzz");
    await userEvent.keyboard("{Escape}");
    expect(box()).toHaveValue(before);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("filters accent-insensitively and says when nothing matches", async () => {
    render(<Harness />);
    await userEvent.click(box());
    await userEvent.keyboard("{Control>}a{/Control}cafe");
    expect(within(await screen.findByRole("listbox")).getAllByRole("option")).toHaveLength(1);
    await userEvent.keyboard("{Control>}a{/Control}nothing-like-this");
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

  it("the input is at least 16 px so iOS does not zoom, and options are 44 px high", async () => {
    render(<Harness />);
    expect(box().className).toContain("text-[16px]"); // the computed size is checked in the calibration e2e
    await userEvent.click(box());
    const option = (await screen.findAllByRole("option"))[0]!;
    expect(option.className).toContain("min-h-11");
  });

  it("offers the none option and the clear button", async () => {
    const onChange = vi.fn();
    render(<Harness initial="none" noneOption={{ id: "none", label: "Choose a sheet type" }} onChange={onChange} />);
    expect(box()).toHaveValue("Choose a sheet type");
    await userEvent.click(box());
    await userEvent.keyboard("{Control>}a{/Control}avery");
    await userEvent.click(screen.getByRole("button", { name: "Clear the search", hidden: true }) /* React Aria hides everything but the list while it is open */);
    expect(box()).toHaveValue("");
    expect(onChange).not.toHaveBeenCalled();
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
