import { registerSearchSource } from "./registry";
import { jobsSource } from "./jobsSource";
import { lookupSource } from "./lookupSource";
import { printersSource } from "./printersSource";

/** The sources the foundation ships; later modules add theirs with `registerSearchSource`. */
registerSearchSource(lookupSource);
registerSearchSource(printersSource);
registerSearchSource(jobsSource);

export { GlobalSearch } from "./GlobalSearch";
export { registerSearchSource, type SearchResult, type SearchSource } from "./registry";
