// App-wide settings shared by every page: live mode and light/dark theme.
// Both are remembered in the browser (localStorage) between visits.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

type Theme = "light" | "dark";

interface Settings {
  live: boolean;
  setLive: (v: boolean) => void;
  theme: Theme;
  toggleTheme: () => void;
  uiLang: "en" | "kn"; // dashboard language for the texts in locales/strings.json
  toggleUiLang: () => void;
}

const SettingsContext = createContext<Settings | null>(null);

function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null; // private mode or blocked storage - just use defaults
  }
}

function store(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [live, setLiveState] = useState(() => readStored("ks-live") === "1");
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = readStored("ks-theme");
    if (saved === "light" || saved === "dark") return saved;
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });

  const [uiLang, setUiLang] = useState<"en" | "kn">(() => (readStored("ks-lang") === "kn" ? "kn" : "en"));

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  useEffect(() => {
    document.documentElement.lang = uiLang;
  }, [uiLang]);

  const toggleUiLang = () =>
    setUiLang((l) => {
      const next = l === "kn" ? "en" : "kn";
      store("ks-lang", next);
      return next;
    });

  const setLive = (v: boolean) => {
    setLiveState(v);
    store("ks-live", v ? "1" : "0");
  };
  const toggleTheme = () =>
    setTheme((t) => {
      const next = t === "dark" ? "light" : "dark";
      store("ks-theme", next);
      return next;
    });

  return <SettingsContext.Provider value={{ live, setLive, theme, toggleTheme, uiLang, toggleUiLang }}>{children}</SettingsContext.Provider>;
}

export function useSettings(): Settings {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error("useSettings must be used inside SettingsProvider");
  return ctx;
}

export const LIVE_REFRESH_MS = 5000;

/**
 * Load data with `loader`. When live mode is on, reload every 5 seconds.
 * Keeps showing the last good data if a refresh fails.
 */
export function useLiveData<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const { live } = useSettings();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const reload = useCallback(async () => {
    try {
      const result = await loaderRef.current();
      setData(result);
      setError(null);
      setUpdatedAt(new Date());
    } catch (e) {
      setError(e as Error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    if (!live) return;
    const id = setInterval(reload, LIVE_REFRESH_MS);
    return () => clearInterval(id);
  }, [live, reload]);

  return { data, error, loading, reload, updatedAt };
}
