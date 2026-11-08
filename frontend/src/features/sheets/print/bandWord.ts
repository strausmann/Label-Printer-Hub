import { useLingui } from "@lingui/react/macro";

type Band = "top" | "bottom" | "right" | "left" | null | undefined;

/** The margin band the sheet ID goes into, in words ("bottom margin"); a band the server did not name reads "margin". */
export function useBandWord(): (band: Band) => string {
  const { t } = useLingui();
  return (band) => {
    switch (band) {
      case "top":
        return t`top margin`;
      case "bottom":
        return t`bottom margin`;
      case "left":
        return t`left margin`;
      case "right":
        return t`right margin`;
      default:
        return t`margin`;
    }
  };
}
