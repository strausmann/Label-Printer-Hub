import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp, SIGNED_IN } from "../../test-utils";
import { apiErrorBody, GEOMETRY_L4736, mockApi, respond, SHEET_TYPE } from "../test-api";

const PRINT_SESSION = { ...SIGNED_IN, scope: "print" as const };
const VERSION = {
  version: 1,
  change_note: null as string | null,
  created_at: "2026-11-01T08:00:00Z",
  geometry: GEOMETRY_L4736,
  geometry_hash: "abc",
  sheets: 3,
};
const DETAIL = { ...SHEET_TYPE, sheets_in_use: 3, versions: [VERSION] };
const CUSTOM = { ...SHEET_TYPE, key: "my-custom", origin: "custom" as const, sheets_in_use: 0, verified: false };
const EXPORT_DOC = {
  format: "label-printer-hub.sheet-type",
  format_version: 1,
  exported_at: "2026-11-01T08:00:00Z",
  exported_by_hub: "test",
  type: { key: "L4736REV", prefix: "L4736", allow_qr: true, product_codes: [], verified: true },
  version: { version: 1, geometry: GEOMETRY_L4736 },
};

const LIST = { "GET /api/sheet-types": [SHEET_TYPE, CUSTOM], "GET /api/sheet-types/L4736REV": DETAIL };

afterEach(() => vi.unstubAllGlobals());

const typeCalls = (calls: { method: string; path: string; search: string }[]) =>
  calls.filter((c) => c.method === "GET" && c.path === "/api/sheet-types");

describe("archive list and filters", () => {
  it("sends every filter of the address as the query", async () => {
    const { calls } = mockApi(LIST);
    await renderApp({ path: "/sheets/archive?page=A4&vendor=Example%20Labels&q=flour&w=45.7&h=21.2&archived=true" });
    await screen.findByRole("link", { name: /L4736REV/ });
    const filtered = typeCalls(calls).find((c) => c.search.includes("q=flour"));
    expect(filtered).toBeDefined();
    expect(new URLSearchParams(filtered!.search).toString()).toBe(
      "page=A4&vendor=Example+Labels&q=flour&w=45.7&h=21.2&include_archived=true",
    );
  });

  it("typing in the search box asks the server for it", async () => {
    const { calls } = mockApi(LIST);
    await renderApp({ path: "/sheets/archive" });
    await screen.findByRole("link", { name: /L4736REV/ });
    await userEvent.type(screen.getByRole("textbox", { name: "Search" }), "flour");
    await waitFor(() => expect(typeCalls(calls).some((c) => c.search === "?q=flour")).toBe(true));
  });

  it("choosing a page size asks the server for it", async () => {
    const { calls } = mockApi(LIST);
    await renderApp({ path: "/sheets/archive" });
    await screen.findByRole("link", { name: /L4736REV/ });
    await userEvent.click(screen.getByRole("button", { name: /Page size/ }));
    await userEvent.click(await screen.findByRole("option", { name: "Letter" }));
    await waitFor(() => expect(typeCalls(calls).some((c) => c.search === "?page=Letter")).toBe(true));
  });

  it("drops filter values that are not valid from the address", async () => {
    const { calls } = mockApi(LIST);
    await renderApp({ path: "/sheets/archive?page=A3&w=-4&h=abc" });
    await screen.findByRole("link", { name: /L4736REV/ });
    expect(typeCalls(calls).every((c) => c.search === "")).toBe(true);
  });

  it("marks types by origin, verification and archive state with words", async () => {
    mockApi({ "GET /api/sheet-types": [SHEET_TYPE, CUSTOM, { ...SHEET_TYPE, key: "old-one", origin: "imported", archived_at: "2026-11-02T00:00:00Z" }] });
    await renderApp({ path: "/sheets/archive?archived=true" });
    const seed = (await screen.findByRole("link", { name: /L4736REV/ })).closest("li")!;
    expect(within(seed).getByText("seed")).toBeVisible();
    expect(within(seed).queryByText("unverified")).toBeNull();
    const custom = screen.getByRole("link", { name: /my-custom/ }).closest("li")!;
    expect(within(custom).getByText("custom")).toBeVisible();
    expect(within(custom).getByText("unverified")).toBeVisible();
    const old = screen.getByRole("link", { name: /old-one/ }).closest("li")!;
    expect(within(old).getByText("imported")).toBeVisible();
    expect(within(old).getByText("archived")).toBeVisible();
  });

  it("says so when nothing matches, and when the list cannot be loaded", async () => {
    mockApi({ "GET /api/sheet-types": [] });
    const first = await renderApp({ path: "/sheets/archive?q=zzz" });
    expect(await screen.findByText("No sheet type matches.")).toBeVisible();
    first.unmount();
    mockApi({ "GET /api/sheet-types": () => respond(403, { detail: "no" }) });
    await renderApp({ path: "/sheets/archive" });
    expect(await screen.findByText("The sheet types could not be loaded.")).toBeVisible();
  });
});

describe("type detail", () => {
  it("shows diagram, geometry, versions with sheet counts and QR permission", async () => {
    mockApi({
      ...LIST,
      "GET /api/sheet-types/L4736REV": {
        ...DETAIL,
        current_version: 2,
        versions: [
          { ...VERSION, version: 2, change_note: "Measured again", sheets: 0 },
          { ...VERSION, version: 1, sheets: 3 },
        ],
      },
    });
    await renderApp({ path: "/sheets/archive?type=L4736REV" });
    expect(await screen.findByRole("heading", { name: "L4736REV" })).toBeVisible();
    expect(screen.getByText("Label size")).toBeVisible();
    const versions = screen.getByRole("table", { name: "Versions" });
    expect(within(versions).getByText("Measured again")).toBeVisible();
    expect(within(versions).getByText("3")).toBeVisible();
    expect(screen.getByText(/QR codes on labels: allowed/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Export" })).toHaveAttribute("href", "/api/sheet-types/L4736REV/export");
  });

  it("links an http(s) source with rel=noopener noreferrer and shows anything else as plain text", async () => {
    mockApi({ ...LIST, "GET /api/sheet-types/L4736REV": { ...DETAIL, source_name: "Vendor datasheet", source_url: "https://example.invalid/sheet.pdf" } });
    const first = await renderApp({ path: "/sheets/archive?type=L4736REV" });
    const link = await screen.findByRole("link", { name: "Vendor datasheet" });
    expect(link).toHaveAttribute("href", "https://example.invalid/sheet.pdf");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    first.unmount();

    mockApi({ ...LIST, "GET /api/sheet-types/L4736REV": { ...DETAIL, source_name: "Vendor datasheet", source_url: "javascript:alert(1)" } });
    await renderApp({ path: "/sheets/archive?type=L4736REV" });
    expect(await screen.findByText(/Vendor datasheet/)).toBeVisible();
    expect(screen.queryByRole("link", { name: "Vendor datasheet" })).toBeNull();
    expect(screen.getByText("javascript:alert(1)")).toBeVisible();
  });

  it("offers delete only for a custom type without sheets", async () => {
    mockApi({ ...LIST, "GET /api/sheet-types/L4736REV": DETAIL, "GET /api/sheet-types/my-custom": { ...CUSTOM, versions: [VERSION] } });
    const first = await renderApp({ path: "/sheets/archive?type=L4736REV" });
    await screen.findByRole("heading", { name: "L4736REV" });
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    first.unmount();
    await renderApp({ path: "/sheets/archive?type=my-custom" });
    await screen.findByRole("heading", { name: "my-custom" });
    expect(screen.getByRole("button", { name: "Delete" })).toBeVisible();
  });

  it("deleting asks first, then deletes and leaves the type", async () => {
    const { calls } = mockApi({ ...LIST, "GET /api/sheet-types/my-custom": { ...CUSTOM, versions: [VERSION] }, "DELETE /api/sheet-types/my-custom": null });
    const { router } = await renderApp({ path: "/sheets/archive?type=my-custom" });
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete type" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
    await waitFor(() => expect(router.state.location.search).not.toHaveProperty("type"));
  });

  it("archives, and an archived type can be brought back", async () => {
    const { calls } = mockApi({
      ...LIST,
      "POST /api/sheet-types/L4736REV/archive": SHEET_TYPE,
      "POST /api/sheet-types/L4736REV/unarchive": SHEET_TYPE,
    });
    const first = await renderApp({ path: "/sheets/archive?type=L4736REV" });
    await userEvent.click(await screen.findByRole("button", { name: "Archive" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/archive"))).toBe(true));
    first.unmount();

    mockApi({
      ...LIST,
      "GET /api/sheet-types/L4736REV": { ...DETAIL, archived_at: "2026-11-02T00:00:00Z" },
      "POST /api/sheet-types/L4736REV/unarchive": SHEET_TYPE,
    });
    await renderApp({ path: "/sheets/archive?type=L4736REV" });
    expect(await screen.findByRole("button", { name: "Unarchive" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Archive" })).toBeNull();
  });

  it("says when the type does not exist", async () => {
    mockApi({ ...LIST, "GET /api/sheet-types/gone": () => respond(404, apiErrorBody("sheet_type_not_found", "Sheet type not found.")) });
    await renderApp({ path: "/sheets/archive?type=gone" });
    expect(await screen.findByText("That sheet type does not exist.")).toBeVisible();
  });
});

describe("edit geometry", () => {
  it("warns that sheets already made keep the older version", async () => {
    mockApi(LIST);
    await renderApp({ path: "/sheets/archive?type=L4736REV" });
    await userEvent.click(await screen.findByRole("button", { name: "Edit geometry" }));
    expect(await screen.findByText("3 sheets keep version 1")).toBeVisible();
  });

  it("does not warn when no sheet uses the current version, and says one sheet in the singular", async () => {
    mockApi({ ...LIST, "GET /api/sheet-types/L4736REV": { ...DETAIL, versions: [{ ...VERSION, sheets: 0 }] } });
    const first = await renderApp({ path: "/sheets/archive?type=L4736REV" });
    await userEvent.click(await screen.findByRole("button", { name: "Edit geometry" }));
    await screen.findByRole("textbox", { name: "What changed" });
    expect(screen.queryByText(/keep version/)).toBeNull();
    first.unmount();
    mockApi({ ...LIST, "GET /api/sheet-types/L4736REV": { ...DETAIL, versions: [{ ...VERSION, sheets: 1 }] } });
    await renderApp({ path: "/sheets/archive?type=L4736REV" });
    await userEvent.click(await screen.findByRole("button", { name: "Edit geometry" }));
    expect(await screen.findByText("1 sheet keeps version 1")).toBeVisible();
  });

  it("saves a new version with the change note", async () => {
    const { calls } = mockApi({ ...LIST, "POST /api/sheet-types/L4736REV/versions": { ...VERSION, version: 2 } });
    await renderApp({ path: "/sheets/archive?type=L4736REV" });
    await userEvent.click(await screen.findByRole("button", { name: "Edit geometry" }));
    const top = screen.getByRole("textbox", { name: "Top margin (mm)" });
    await userEvent.clear(top);
    await userEvent.type(top, "21,8");
    await userEvent.type(screen.getByRole("textbox", { name: "What changed" }), "Measured with a ruler");
    await userEvent.click(screen.getByRole("button", { name: "Save new version" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const body = JSON.parse(calls.find((c) => c.method === "POST")!.body!);
    expect(body.change_note).toBe("Measured with a ruler");
    expect(body.geometry).toMatchObject({ margin_top: 21.8, cols: 4, rows: 12, label_w: 45.7, page_size: "A4", shape: "rectangle" });
  });

  it("asks for the change note and a sensible number before sending anything", async () => {
    const { calls } = mockApi(LIST);
    await renderApp({ path: "/sheets/archive?type=L4736REV" });
    await userEvent.click(await screen.findByRole("button", { name: "Edit geometry" }));
    await userEvent.click(screen.getByRole("button", { name: "Save new version" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Describe what changed.");
    await userEvent.type(screen.getByRole("textbox", { name: "What changed" }), "x");
    const cols = screen.getByRole("textbox", { name: "Columns" });
    await userEvent.clear(cols);
    await userEvent.type(cols, "2.5");
    await userEvent.click(screen.getByRole("button", { name: "Save new version" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Columns must be a whole number from 1 to 400.");
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  const refuseGeometry = (field: string, reason: string) =>
    mockApi({
      ...LIST,
      "POST /api/sheet-types/L4736REV/versions": () => respond(422, apiErrorBody("invalid_geometry", "Invalid geometry", { field, reason })),
    });
  const saveWithNote = async () => {
    await userEvent.click(await screen.findByRole("button", { name: "Edit geometry" }));
    await userEvent.type(screen.getByRole("textbox", { name: "What changed" }), "x");
    await userEvent.click(screen.getByRole("button", { name: "Save new version" }));
  };

  it("shows the server's geometry complaint in words, marks the field, and never the raw keyword", async () => {
    refuseGeometry("cols", "grid is wider than the page");
    await renderApp({ path: "/sheets/archive?type=L4736REV" });
    await saveWithNote();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The grid does not fit on the page: it is wider than the page.");
    expect(alert).not.toHaveTextContent("grid is wider");
    expect(alert).not.toHaveTextContent("cols:");
    expect(screen.getByRole("textbox", { name: "Columns" })).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("textbox", { name: "Rows" })).not.toHaveAttribute("aria-invalid", "true");
  });

  it("says in German what the server meant", async () => {
    refuseGeometry("pitch_x", "must not be smaller than label_w");
    await renderApp({ path: "/sheets/archive?type=L4736REV", language: "de" });
    await userEvent.click(await screen.findByRole("button", { name: "Maße bearbeiten" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Was sich geändert hat" }), "x");
    await userEvent.click(screen.getByRole("button", { name: "Neue Version speichern" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Der horizontale Abstand darf nicht kleiner sein als die Etikettenbreite.");
  });

  it("an unknown reason gets a generic sentence with the keyword only as a detail", async () => {
    refuseGeometry("rows", "something new");
    await renderApp({ path: "/sheets/archive?type=L4736REV" });
    await saveWithNote();
    expect(await screen.findByRole("alert")).toHaveTextContent("The server did not accept this value. The number of rows (something new).");
  });

  it("the server refusing an unchanged geometry is explained", async () => {
    refuseGeometry("geometry", "unchanged");
    await renderApp({ path: "/sheets/archive?type=L4736REV" });
    await saveWithNote();
    expect(await screen.findByRole("alert")).toHaveTextContent("The measurements are the same as in the current version. Change something first.");
  });
});

describe("edit details and create", () => {
  it("patches only what changed", async () => {
    const { calls } = mockApi({ ...LIST, "PATCH /api/sheet-types/L4736REV": SHEET_TYPE });
    await renderApp({ path: "/sheets/archive?type=L4736REV" });
    await userEvent.click(await screen.findByRole("button", { name: "Edit details" }));
    const vendor = screen.getByRole("textbox", { name: "Vendor" });
    await userEvent.clear(vendor);
    await userEvent.type(vendor, "Other Labels");
    await userEvent.click(screen.getByRole("button", { name: "Save details" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PATCH")!.body!)).toEqual({ vendor: "Other Labels" });
  });

  it("does not let the prefix change once sheets exist", async () => {
    mockApi(LIST);
    await renderApp({ path: "/sheets/archive?type=L4736REV" });
    await userEvent.click(await screen.findByRole("button", { name: "Edit details" }));
    expect(screen.getByRole("textbox", { name: "Code prefix" })).toHaveAttribute("readonly");
  });

  it("creates a type from key, prefix and measurements", async () => {
    const { calls } = mockApi({ ...LIST, "POST /api/sheet-types": CUSTOM });
    await renderApp({ path: "/sheets/archive" });
    await userEvent.click(await screen.findByRole("button", { name: "New type" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Key" }), "my-custom");
    await userEvent.type(screen.getByRole("textbox", { name: "Code prefix" }), "mycu");
    for (const [name, value] of [
      ["Columns", "3"],
      ["Rows", "8"],
      ["Label width (mm)", "63,5"],
      ["Label height (mm)", "33.9"],
      ["Horizontal pitch (mm)", "66"],
      ["Vertical pitch (mm)", "34"],
      ["Top margin (mm)", "15"],
      ["Left margin (mm)", "7"],
    ] as const) {
      await userEvent.type(screen.getByRole("textbox", { name }), value);
    }
    await userEvent.click(screen.getByRole("button", { name: "Create type" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "POST")!.body!)).toMatchObject({
      key: "my-custom",
      prefix: "MYCU",
      geometry: { cols: 3, rows: 8, label_w: 63.5, label_h: 33.9, pitch_x: 66, pitch_y: 34, margin_top: 15, margin_left: 7, page_size: "A4", shape: "rectangle", corner_radius: null },
    });
  }, 30_000);

  it("refuses a key or prefix of the wrong shape, and shows a taken key in words", async () => {
    const { calls } = mockApi({
      ...LIST,
      "POST /api/sheet-types": () => respond(409, apiErrorBody("type_exists", "A sheet type with this key already exists.")),
    });
    await renderApp({ path: "/sheets/archive" });
    await userEvent.click(await screen.findByRole("button", { name: "New type" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Key" }), "Bad Key");
    await userEvent.click(screen.getByRole("button", { name: "Create type" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The key uses lowercase letters, digits and dashes");
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });
});

describe("import", () => {
  const paste = async (text: string) => {
    await userEvent.click(await screen.findByRole("button", { name: "Import type" }));
    const box = await screen.findByRole("textbox", { name: "Export file contents" });
    await userEvent.click(box);
    await userEvent.paste(text);
  };
  const submit = () => userEvent.click(screen.getByRole("button", { name: "Import" }));
  const posts = (calls: { method: string; path: string; search: string }[]) => calls.filter((c) => c.method === "POST");

  it.each([
    ["created", "Created the type L4736REV."],
    ["unchanged", "Nothing changed: L4736REV already has this geometry."],
    ["version_added", "Added version 2 to L4736REV."],
    ["created_as_new_key", "Created the type L4736REV as a new key."],
  ])("reports the outcome %s", async (outcome, words) => {
    mockApi({ ...LIST, "POST /api/sheet-types/import": respond(201, { key: "L4736REV", version: outcome === "version_added" ? 2 : 1, outcome }) });
    await renderApp({ path: "/sheets/archive" });
    await paste(JSON.stringify(EXPORT_DOC));
    await submit();
    expect(await screen.findByRole("status")).toHaveTextContent(words);
  });

  it("import conflict offers the two modes", async () => {
    const answers = [
      respond(409, apiErrorBody("type_exists", "A sheet type with this key already exists.")),
      respond(201, { key: "copy-key", version: 1, outcome: "created_as_new_key" }),
    ];
    const { calls } = mockApi({ ...LIST, "POST /api/sheet-types/import": () => answers.shift() });
    await renderApp({ path: "/sheets/archive" });
    await paste(JSON.stringify(EXPORT_DOC));
    await submit();
    expect(await screen.findByRole("button", { name: "Add as new version" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Import under a new key" })).toBeVisible();
    expect(posts(calls)[0]!.search).toBe("");

    await userEvent.click(screen.getByRole("button", { name: "Import under a new key" }));
    await userEvent.type(screen.getByRole("textbox", { name: "New key" }), "copy-key");
    await userEvent.type(screen.getByRole("textbox", { name: "New code prefix (optional)" }), "cpy");
    await userEvent.click(screen.getByRole("button", { name: "Import with the new key" }));
    await waitFor(() => expect(posts(calls)).toHaveLength(2));
    expect(new URLSearchParams(posts(calls)[1]!.search).toString()).toBe("mode=as_new_key&new_key=copy-key&new_prefix=CPY");
    expect(await screen.findByRole("status")).toHaveTextContent("Created the type copy-key as a new key.");
  });

  it("adds a version when asked to", async () => {
    const answers = [
      respond(409, apiErrorBody("type_exists", "exists")),
      respond(201, { key: "L4736REV", version: 2, outcome: "version_added" }),
    ];
    const { calls } = mockApi({ ...LIST, "POST /api/sheet-types/import": () => answers.shift() });
    await renderApp({ path: "/sheets/archive" });
    await paste(JSON.stringify(EXPORT_DOC));
    await submit();
    await userEvent.click(await screen.findByRole("button", { name: "Add as new version" }));
    await waitFor(() => expect(posts(calls)).toHaveLength(2));
    expect(posts(calls)[1]!.search).toBe("?mode=new_version");
    expect(await screen.findByRole("status")).toHaveTextContent("Added version 2 to L4736REV.");
  });

  it("asks for another prefix when the prefix is taken, and keeps the chosen mode", async () => {
    const answers = [
      respond(409, apiErrorBody("type_exists", "exists")),
      respond(409, apiErrorBody("prefix_taken", "taken", { reason: "prefix_in_use" })),
      respond(201, { key: "copy-key", version: 1, outcome: "created_as_new_key" }),
    ];
    const { calls } = mockApi({ ...LIST, "POST /api/sheet-types/import": () => answers.shift() });
    await renderApp({ path: "/sheets/archive" });
    await paste(JSON.stringify(EXPORT_DOC));
    await submit();
    await userEvent.click(await screen.findByRole("button", { name: "Import under a new key" }));
    await userEvent.type(screen.getByRole("textbox", { name: "New key" }), "copy-key");
    await userEvent.click(screen.getByRole("button", { name: "Import with the new key" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Another type already uses this code prefix");
    const prefix = screen.getByRole("textbox", { name: "New code prefix" });
    expect(prefix).toBeRequired();
    await userEvent.type(prefix, "zz9");
    await userEvent.click(screen.getByRole("button", { name: "Import with the new key" }));
    await waitFor(() => expect(posts(calls)).toHaveLength(3));
    expect(new URLSearchParams(posts(calls)[2]!.search).toString()).toBe("mode=as_new_key&new_key=copy-key&new_prefix=ZZ9");
  });

  it("import errors are shown, not thrown", async () => {
    const answers = [
      respond(422, apiErrorBody("invalid_import", "invalid", { errors: ["type.key", "version.geometry.cols"] })),
      respond(413, apiErrorBody("import_too_large", "too large")),
    ];
    const { calls } = mockApi({ ...LIST, "POST /api/sheet-types/import": () => answers.shift() });
    await renderApp({ path: "/sheets/archive" });
    await paste(JSON.stringify(EXPORT_DOC));
    await submit();
    const invalid = await screen.findByRole("alert");
    expect(invalid).toHaveTextContent("This is not a valid sheet type export.");
    expect(invalid).toHaveTextContent("type.key");
    expect(invalid).toHaveTextContent("version.geometry.cols");
    await submit();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("The server refused the file: it is larger than 64 KB."));
    expect(posts(calls)).toHaveLength(2);
    expect(screen.getByRole("textbox", { name: "Export file contents" })).toBeVisible();
  });

  it("does not send text that is not JSON", async () => {
    const { calls } = mockApi(LIST);
    await renderApp({ path: "/sheets/archive" });
    await paste("this is { not json");
    await submit();
    expect(await screen.findByRole("alert")).toHaveTextContent("That text is not valid JSON.");
    expect(posts(calls)).toHaveLength(0);
  });

  it("does not send an empty box, nor a JSON value that is not an object", async () => {
    const { calls } = mockApi(LIST);
    await renderApp({ path: "/sheets/archive" });
    await userEvent.click(await screen.findByRole("button", { name: "Import type" }));
    await submit();
    expect(await screen.findByRole("alert")).toHaveTextContent("Paste the export file or choose it.");
    await userEvent.click(screen.getByRole("textbox", { name: "Export file contents" }));
    await userEvent.paste("[1, 2]");
    await submit();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("This is not a sheet type export file."));
    expect(posts(calls)).toHaveLength(0);
  });

  it("checks the 64 KB limit before upload, for pasted text and for a chosen file", async () => {
    const { calls } = mockApi(LIST);
    await renderApp({ path: "/sheets/archive" });
    await userEvent.click(await screen.findByRole("button", { name: "Import type" }));
    const big = new File([new Uint8Array(65537)], "big.json", { type: "application/json" });
    await userEvent.upload(screen.getByLabelText("Or choose an export file"), big);
    expect(await screen.findByRole("alert")).toHaveTextContent("The file is larger than 64 KB.");
    expect(posts(calls)).toHaveLength(0);

    await userEvent.click(screen.getByRole("textbox", { name: "Export file contents" }));
    await userEvent.paste("é".repeat(33000)); // 66 000 bytes in 33 000 characters
    await submit();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("The text is larger than 64 KB."));
    expect(posts(calls)).toHaveLength(0);
  }, 30_000);

  it("reads a chosen file into the box", async () => {
    mockApi(LIST);
    await renderApp({ path: "/sheets/archive" });
    await userEvent.click(await screen.findByRole("button", { name: "Import type" }));
    await userEvent.upload(screen.getByLabelText("Or choose an export file"), new File([JSON.stringify(EXPORT_DOC)], "x.json", { type: "application/json" }));
    await waitFor(() => expect((screen.getByRole("textbox", { name: "Export file contents" }) as HTMLTextAreaElement).value).toContain("label-printer-hub.sheet-type"));
  });

  it("shows a network failure in words", async () => {
    mockApi({ ...LIST, "POST /api/sheet-types/import": () => { throw new TypeError("offline"); } });
    await renderApp({ path: "/sheets/archive" });
    await paste(JSON.stringify(EXPORT_DOC));
    await submit();
    expect(await screen.findByRole("alert")).toHaveTextContent("The server cannot be reached.");
  });
});

describe("a session that may only read and print", () => {
  it("non-admin sees no write buttons", async () => {
    mockApi(LIST);
    await renderApp({ path: "/sheets/archive?type=L4736REV", session: PRINT_SESSION });
    await screen.findByRole("heading", { name: "L4736REV" });
    for (const name of ["New type", "Import type", "Edit geometry", "Edit details", "Archive", "Unarchive", "Delete"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    // Reading stays possible: the diagram, the versions and the export download.
    expect(screen.getByRole("table", { name: "Versions" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Export" })).toBeVisible();
  });
});

describe("filters, as a person uses them", () => {
  it("choosing a vendor asks the server for it", async () => {
    const { calls } = mockApi(LIST);
    await renderApp({ path: "/sheets/archive" });
    await screen.findByRole("link", { name: /L4736REV/ });
    await userEvent.click(screen.getByRole("button", { name: /Vendor/ }));
    await userEvent.click(await screen.findByRole("option", { name: "Example Labels" }));
    await waitFor(() => expect(typeCalls(calls).some((c) => c.search === "?vendor=Example+Labels")).toBe(true));
  });

  it("typing a label size (with a decimal comma) asks the server for it", async () => {
    const { calls } = mockApi(LIST);
    await renderApp({ path: "/sheets/archive" });
    await screen.findByRole("link", { name: /L4736REV/ });
    await userEvent.type(screen.getByRole("textbox", { name: "Label width (mm)" }), "45,7");
    await userEvent.type(screen.getByRole("textbox", { name: "Label height (mm)" }), "21.2");
    await waitFor(() => expect(typeCalls(calls).some((c) => c.search === "?w=45.7&h=21.2")).toBe(true));
  });

  it("the boxes follow the address when it changes from outside", async () => {
    mockApi(LIST);
    const { router } = await renderApp({ path: "/sheets/archive?q=first" });
    const search = await screen.findByRole("textbox", { name: "Search" });
    expect(search).toHaveValue("first");
    await act(async () => {
      await router.navigate({ to: "/sheets/archive", search: { q: "second", w: 45.7 } });
    });
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Search" })).toHaveValue("second"));
    expect(screen.getByRole("textbox", { name: "Label width (mm)" })).toHaveValue("45.7");
    // And it stays so: the old text is not written back over the address.
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(router.state.location.search).toMatchObject({ q: "second", w: 45.7 });
  });

  it("a commit that lands after more typing does not eat the keystrokes", async () => {
    mockApi(LIST);
    const { router } = await renderApp({ path: "/sheets/archive" });
    const search = await screen.findByRole("textbox", { name: "Search" });
    // The address answers 300 ms late: the commit of "4" arrives after "45" was typed.
    const navigate = router.navigate.bind(router);
    router.navigate = ((options: Parameters<typeof navigate>[0]) =>
      new Promise((resolve) => setTimeout(() => resolve(navigate(options)), 300))) as typeof router.navigate;
    await userEvent.type(search, "4");
    await new Promise((resolve) => setTimeout(resolve, 260));
    await userEvent.type(search, "5");
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(search).toHaveValue("45");
    await waitFor(() => expect(router.state.location.search).toMatchObject({ q: "45" }), { timeout: 3000 });
    expect(search).toHaveValue("45");
  });

  it("caps the search at what the API takes: 100 characters in the box, and in a hand-edited address", async () => {
    const { calls } = mockApi(LIST);
    await renderApp({ path: `/sheets/archive?q=${"a".repeat(130)}&vendor=${"v".repeat(250)}` });
    await screen.findByRole("link", { name: /L4736REV/ });
    expect(screen.getByRole("textbox", { name: "Search" })).toHaveAttribute("maxlength", "100");
    const asked = typeCalls(calls).map((c) => new URLSearchParams(c.search));
    expect(asked.every((p) => (p.get("q") ?? "").length <= 100 && (p.get("vendor") ?? "").length <= 200)).toBe(true);
    expect(asked.some((p) => p.get("q") === "a".repeat(100) && p.get("vendor") === "v".repeat(200))).toBe(true);
  });

  it("the filter panel can be folded, starts folded without a filter and counts the ones in use", async () => {
    mockApi(LIST);
    const first = await renderApp({ path: "/sheets/archive" });
    const toggle = await screen.findByRole("button", { name: "Filters" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    first.unmount();

    await renderApp({ path: "/sheets/archive?q=flour&page=A4&archived=true" });
    const open = await screen.findByRole("button", { name: "Filters (3 active)" });
    expect(open).toHaveAttribute("aria-expanded", "true");
    expect(open).toHaveAttribute("aria-controls", "archive-filters");
  });
});

describe("versions and imports that touch the open type", () => {
  it("lists the newest version first and marks the current one", async () => {
    mockApi({
      ...LIST,
      "GET /api/sheet-types/L4736REV": {
        ...DETAIL,
        current_version: 3,
        versions: [1, 3, 2].map((version) => ({ ...VERSION, version, change_note: `note ${version}` })),
      },
    });
    await renderApp({ path: "/sheets/archive?type=L4736REV" });
    const table = await screen.findByRole("table", { name: "Versions" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getByRole("rowheader").textContent)).toEqual(["3current", "2", "1"]);
  });

  it("an import that adds a version shows it in the open type, not the cached one", async () => {
    let versions = [VERSION];
    let posts = 0;
    mockApi({
      ...LIST,
      "GET /api/sheet-types/L4736REV": () => ({ ...DETAIL, current_version: versions.length, versions }),
      "POST /api/sheet-types/import": () => {
        if (posts++ === 0) return respond(409, apiErrorBody("type_exists", "exists"));
        versions = [{ ...VERSION, version: 2, change_note: "imported geometry" }, VERSION];
        return respond(201, { key: "L4736REV", version: 2, outcome: "version_added" });
      },
    });
    await renderApp({ path: "/sheets/archive?type=L4736REV" });
    await screen.findByRole("table", { name: "Versions" });
    await userEvent.click(screen.getByRole("button", { name: "Import type" }));
    await userEvent.click(await screen.findByRole("textbox", { name: "Export file contents" }));
    await userEvent.paste(JSON.stringify(EXPORT_DOC));
    await userEvent.click(screen.getByRole("button", { name: "Import" }));
    await userEvent.click(await screen.findByRole("button", { name: "Add as new version" }));
    await userEvent.click(await screen.findByRole("button", { name: "Show the type" }));
    expect(await screen.findByText("imported geometry")).toBeVisible();
  });

  it("a conflict sentence never prints an object as the key", async () => {
    mockApi({ ...LIST, "POST /api/sheet-types/import": () => respond(409, apiErrorBody("type_exists", "exists")) });
    await renderApp({ path: "/sheets/archive" });
    await userEvent.click(await screen.findByRole("button", { name: "Import type" }));
    await userEvent.click(await screen.findByRole("textbox", { name: "Export file contents" }));
    await userEvent.paste(JSON.stringify({ ...EXPORT_DOC, type: { ...EXPORT_DOC.type, key: { a: 1 } } }));
    await userEvent.click(screen.getByRole("button", { name: "Import" }));
    const text = await screen.findByText(/already exists/);
    expect(text).not.toHaveTextContent("[object Object]");
  });

  it("checks the new key and the new prefix before sending them", async () => {
    const { calls } = mockApi({ ...LIST, "POST /api/sheet-types/import": () => respond(409, apiErrorBody("type_exists", "exists")) });
    await renderApp({ path: "/sheets/archive" });
    await userEvent.click(await screen.findByRole("button", { name: "Import type" }));
    await userEvent.click(await screen.findByRole("textbox", { name: "Export file contents" }));
    await userEvent.paste(JSON.stringify(EXPORT_DOC));
    await userEvent.click(screen.getByRole("button", { name: "Import" }));
    await userEvent.click(await screen.findByRole("button", { name: "Import under a new key" }));
    const before = calls.filter((c) => c.method === "POST").length;
    await userEvent.type(screen.getByRole("textbox", { name: "New key" }), "Bad Key");
    await userEvent.click(screen.getByRole("button", { name: "Import with the new key" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The key uses lowercase letters");
    await userEvent.clear(screen.getByRole("textbox", { name: "New key" }));
    await userEvent.type(screen.getByRole("textbox", { name: "New key" }), "good-key");
    await userEvent.type(screen.getByRole("textbox", { name: "New code prefix (optional)" }), "1x");
    await userEvent.click(screen.getByRole("button", { name: "Import with the new key" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("The code prefix is 2 to 10 capital letters or digits"));
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(before);
  });
});
