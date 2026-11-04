import { resolve } from "node:path";

/** Two throw-away hubs: one with an admin key, one waiting for its first admin key (D7). */
export const MAIN = {
  port: 8765,
  url: "http://localhost:8765",
  keyFile: resolve(import.meta.dirname, ".tmp", "main.key"),
};
export const BOOTSTRAP = {
  port: 8766,
  url: "http://localhost:8766",
  keyFile: resolve(import.meta.dirname, ".tmp", "bootstrap.key"),
};
