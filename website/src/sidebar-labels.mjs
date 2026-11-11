// German label for every sidebar group. A group whose label is missing here fails the build
// (see group() in astro.config.mjs), so the German sidebar can never fall back to English.
export const sidebarLabels = {
  Try: "Ausprobieren",
  Install: "Installieren",
  Using: "Benutzen",
  Admin: "Verwalten",
  Upgrades: "Aktualisieren",
  Integrations: "Integrationen",
  Developers: "Entwickeln",
  Reference: "Referenz",
};
