import { createContext, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { readHistoryToken, writeHistoryToken } from "./lib/historyToken";

interface HistoryAccessState {
  token: string;
  unlock: (token: string) => void;
  lock: () => void;
}

const Context = createContext<HistoryAccessState | null>(null);

export function HistoryAccessProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState(readHistoryToken);
  const value = useMemo(
    () => ({
      token,
      unlock: (next: string) => {
        writeHistoryToken(next);
        setToken(next);
      },
      lock: () => {
        writeHistoryToken("");
        setToken("");
      },
    }),
    [token],
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useHistoryAccess(): HistoryAccessState {
  const value = useContext(Context);
  if (!value) throw new Error("HistoryAccessProvider missing");
  return value;
}
