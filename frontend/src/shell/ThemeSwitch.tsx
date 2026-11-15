// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useState } from "react";
import { Button, Radio, RadioGroup } from "react-aria-components";
import { MoonIcon, SunIcon, SystemIcon } from "./icons";
import { applyTheme, isTheme, readTheme, storeTheme, type ThemeChoice } from "./theme";

/** System / light / dark, remembered in `localStorage` (`lph.theme`) and set as `data-theme`. */
export function ThemeSwitch() {
  const { t } = useLingui();
  const [choice, setChoice] = useState<ThemeChoice>(readTheme);

  const options: { value: ThemeChoice; label: string; icon: React.ReactNode }[] = [
    { value: "system", label: t`System theme`, icon: <SystemIcon width={18} height={18} /> },
    { value: "light", label: t`Light theme`, icon: <SunIcon width={18} height={18} /> },
    { value: "dark", label: t`Dark theme`, icon: <MoonIcon width={18} height={18} /> },
  ];

  const order: ThemeChoice[] = ["system", "light", "dark"];
  const current = options.find((o) => o.value === choice) ?? options[0]!;
  const apply = (value: ThemeChoice) => {
    setChoice(value);
    storeTheme(value);
    applyTheme(value);
  };
  const word: Record<ThemeChoice, string> = {
    system: t({ message: "system", context: "the chosen theme, after the word Theme" }),
    light: t({ message: "light", context: "the chosen theme, after the word Theme" }),
    dark: t({ message: "dark", context: "the chosen theme, after the word Theme" }),
  };

  const chosen = word[choice];

  return (
    <>
    {/* Below 400 px the three-way switch would push the other controls off the screen (320 px): one button cycles through it. */}
    <Button
      aria-label={t`Theme: ${chosen}`}
      onPress={() => apply(order[(order.indexOf(choice) + 1) % order.length]!)}
      className="press flex size-11 items-center justify-center rounded-r2 text-ink-2 transition-colors duration-150 hover:bg-sunken hover:text-ink data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-1 data-[focus-visible]:outline-link min-[400px]:hidden"
    >
      {current.icon}
    </Button>
    <RadioGroup
      aria-label={t`Theme`}
      orientation="horizontal"
      value={choice}
      onChange={(value) => {
        if (isTheme(value)) apply(value);
      }}
      className="hidden rounded-r2 bg-sunken p-0.5 min-[400px]:flex"
    >
      {options.map((option) => (
        <Radio
          key={option.value}
          value={option.value}
          aria-label={option.label}
          className="press flex size-9 cursor-pointer items-center justify-center rounded-r1 text-ink-2 transition-colors duration-150 data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-1 data-[focus-visible]:outline-link data-[selected]:bg-surface data-[selected]:text-ink"
        >
          {option.icon}
        </Radio>
      ))}
    </RadioGroup>
    </>
  );
}
