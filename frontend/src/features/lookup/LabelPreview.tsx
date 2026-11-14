// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { ApiError } from "../../api/client";
import type { LayoutOptions } from "../layout/ql";
import type { usePreviewImage } from "./api";

type Preview = ReturnType<typeof usePreviewImage>;

/** What a failed preview means for the person, when the server said something specific; else null. */
function usePreviewProblem(error: unknown, layout: LayoutOptions | undefined): string | null {
  const { t } = useLingui();
  if (!(error instanceof ApiError)) return null;
  if (error.code === "qr_payload_too_long") {
    const length = Number(error.errorDetail?.length);
    const max = Number(error.errorDetail?.max_bytes);
    return Number.isFinite(length) && Number.isFinite(max)
      ? t`The link in the QR code is ${length} bytes long, but this layout holds at most ${max} bytes. Pick another arrangement or a shorter link.`
      : t`The link in the QR code is too long for this layout.`;
  }
  // Only when the person asked for across; for any other print an unsupported tape stays the plain "no preview".
  if (error.code === "unsupported_tape" && layout?.orientation === "across") return t`The across direction is only available for 62 mm tape. Pick along or load 62 mm tape.`;
  return null;
}

/**
 * The label as the printer would draw it: 1 bit, at its real pixel size, scaled up without smoothing so single
 * dots stay crisp. A picture of an earlier choice stays (dimmed) while the next one is drawn.
 */
export function LabelPreview({ preview, layout }: { preview: Preview; layout?: LayoutOptions }) {
  const { t } = useLingui();
  const problem = usePreviewProblem(preview.error, layout);
  return (
    <div
      aria-busy={preview.isRefreshing || preview.isPending}
      className="grid min-h-32 place-items-center overflow-x-auto rounded-r2 bg-sunken p-4"
    >
      {preview.url ? (
        <img
          src={preview.url}
          alt={t`Label preview`}
          className={`max-w-full bg-white transition-opacity duration-150 [image-rendering:pixelated] ${preview.isRefreshing ? "opacity-50" : ""}`}
        />
      ) : problem ? (
        <p role="alert" className="max-w-prose text-ink">{problem}</p>
      ) : preview.isError ? (
        <p className="text-ink-2">{t`No preview for this tape.`}</p>
      ) : (
        <p role="status" className="text-ink-2">{t`Drawing the label…`}</p>
      )}
    </div>
  );
}
