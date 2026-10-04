const KEY = "rootlens-history-token";

export function readHistoryToken(): string {
  try {
    return sessionStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

export function writeHistoryToken(value: string): void {
  try {
    if (value) sessionStorage.setItem(KEY, value);
    else sessionStorage.removeItem(KEY);
  } catch {
    /* Private browsing may disable storage; in-memory state still works. */
  }
}
