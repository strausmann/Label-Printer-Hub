// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Row } from "./Row";

describe("Row", () => {
  it("pairs a label with its value and keeps the label narrow on phones", () => {
    render(
      <dl>
        <Row label="Licence">AGPL-3.0-or-later</Row>
      </dl>,
    );
    const label = screen.getByText("Licence");
    expect(label.tagName).toBe("DT");
    expect(label.className).toMatch(/\bw-32\b/);
    expect(label.className).toMatch(/\bsm:w-40\b/);
    expect(screen.getByText("AGPL-3.0-or-later").tagName).toBe("DD");
  });
});
