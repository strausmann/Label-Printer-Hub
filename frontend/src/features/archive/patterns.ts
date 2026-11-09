/** The shapes the server accepts for a type's key and code prefix (backend `sheets/naming.py`). */
export const KEY = /^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/;
export const PREFIX = /^[A-Z][A-Z0-9]{1,9}$/;
