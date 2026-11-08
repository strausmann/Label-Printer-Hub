import { useLingui } from "@lingui/react/macro";

type Band = "top" | "bottom" | "right" | "left" | null | undefined;

/**
 * "Sheet ID in the bottom margin" as one whole message per band, so a language with cases or
 * another word order can phrase each one on its own. A band the server did not name reads "margin".
 */
export function useSheetIdBand(): (band: Band) => string {
  const { t } = useLingui();
  return (band) => {
    switch (band) {
      case "top":
        return t`Sheet ID in the top margin`;
      case "bottom":
        return t`Sheet ID in the bottom margin`;
      case "left":
        return t`Sheet ID in the left margin`;
      case "right":
        return t`Sheet ID in the right margin`;
      default:
        return t`Sheet ID in the margin`;
    }
  };
}
