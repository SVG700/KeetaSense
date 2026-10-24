// Page frame: header with navigation, live-mode toggle and theme toggle.
import { useCallback, useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { api } from "../api";
import { LIVE_REFRESH_MS, useLiveData, useSettings } from "../settings";

/** Thin bar under the header: which detector produced the counts on this screen. */
function DetectorBanner() {
  const { data } = useLiveData(api.health);
  const d = data?.detector;
  if (!d) return null; // backend unreachable: the page itself shows the error
  const demo = d.mode === "demo_detector";
  return (
    <div
      className={`border-b text-sm ${demo
        ? "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"
        : "border-leaf-600/30 bg-leaf-50 text-leaf-900 dark:border-leaf-800 dark:bg-leaf-900/30 dark:text-leaf-100"}`}
      role="status"
    >
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-2 px-4 py-1.5">
        <span aria-hidden>{demo ? "⚠" : "✓"}</span>
        <span className="font-medium">{d.label}</span>
        {demo && <span className="text-xs opacity-80">— counts come from simple blob counting, not the AI model{d.reason === "weights failed to load" ? " (the weights file failed to load - see backend log)" : ""}.</span>}
        {!demo && d.synthetic_data && <span className="text-xs font-semibold">— trained on SYNTHETIC data only!</span>}
        <NavLink to="/model" className="ml-auto text-xs underline underline-offset-2">Model details</NavLink>
      </div>
    </div>
  );
}

/** Hidden demo helper: a faint "↺" in the footer (or Alt+Shift+R) restores the seeded demo data. */
function ResetDemoButton() {
  const [state, setState] = useState<"idle" | "busy" | "error">("idle");
  const [message, setMessage] = useState("");

  const reset = useCallback(async () => {
    if (!window.confirm("Reset the demo? All current data is replaced by the 14-day simulated history.")) return;
    setState("busy");
    setMessage("Resetting demo data…");
    try {
      const r = await api.resetDemo();
      setMessage(`Demo reset: ${r.sections_created} simulated sections in ${r.seconds} s. Reloading…`);
      window.setTimeout(() => window.location.reload(), 800);
    } catch (e) {
      setState("error");
      setMessage(`Reset failed: ${(e as Error).message}`);
    }
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.altKey && e.shiftKey && e.key.toLowerCase() === "r") reset();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [reset]);

  return (
    <>
      <button onClick={reset} disabled={state === "busy"} title="Reset demo data (Alt+Shift+R)"
              aria-label="Reset demo data" className="ml-1 opacity-30 hover:opacity-100 focus:opacity-100">
        ↺
      </button>
      {message && <div role="status" className={`mt-2 ${state === "error" ? "text-red-700 dark:text-red-400" : ""}`}>{message}</div>}
    </>
  );
}

function NavItem({ to, children }: { to: string; children: string }) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) =>
        `rounded-lg px-3 py-1.5 text-sm font-medium transition ${
          isActive ? "bg-leaf-700 text-white" : "text-stone-700 hover:bg-stone-200 dark:text-stone-300 dark:hover:bg-stone-800"
        }`
      }
    >
      {children}
    </NavLink>
  );
}

export default function Layout() {
  const { live, setLive, theme, toggleTheme } = useSettings();
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-stone-200 bg-white/90 backdrop-blur dark:border-stone-800 dark:bg-stone-950/90">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
          <NavLink to="/" className="flex items-center gap-2">
            <img src="/favicon.svg" alt="" className="h-8 w-8" />
            <span className="text-lg font-bold tracking-tight">
              Keeta<span className="text-leaf-700 dark:text-leaf-500">Sense</span>
            </span>
          </NavLink>
          <nav className="flex flex-wrap gap-1">
            <NavItem to="/">Overview</NavItem>
            <NavItem to="/phone-check">Phone check</NavItem>
            <NavItem to="/model">Model</NavItem>
            <NavItem to="/settings">Settings</NavItem>
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={() => setLive(!live)}
              aria-pressed={live}
              title={`Refresh every ${LIVE_REFRESH_MS / 1000} seconds`}
              className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm font-medium transition ${
                live
                  ? "border-leaf-600 bg-leaf-50 text-leaf-800 dark:bg-leaf-900/40 dark:text-leaf-100"
                  : "border-stone-300 text-stone-600 dark:border-stone-700 dark:text-stone-300"
              }`}
            >
              <span className={`h-2 w-2 rounded-full ${live ? "animate-pulse bg-leaf-500" : "bg-stone-400"}`} aria-hidden />
              Live {live ? "on" : "off"}
            </button>
            <button
              onClick={toggleTheme}
              className="rounded-full border border-stone-300 px-3 py-1.5 text-sm dark:border-stone-700"
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
            >
              {theme === "dark" ? "☀ Light" : "☾ Dark"}
            </button>
          </div>
        </div>
        <DetectorBanner />
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Outlet />
      </main>
      <footer className="mx-auto max-w-6xl px-4 pb-8 text-xs text-stone-500">
        KeetaSense · AI insect counting for yellow sticky traps · Chip to Crop hackathon (Presidency University × ICAR-IIHR).
        Thresholds are placeholders until confirmed with IIHR (see Settings).
        <ResetDemoButton />
      </footer>
    </div>
  );
}
