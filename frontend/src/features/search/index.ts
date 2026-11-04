import { registerSearchSource } from "./registry";
import { lookupSource } from "./lookupSource";

/** The sources the foundation ships; later modules add theirs with `registerSearchSource`. */
registerSearchSource(lookupSource);

export { GlobalSearch } from "./GlobalSearch";
export { registerSearchSource, type SearchResult, type SearchSource } from "./registry";
