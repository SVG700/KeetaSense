// Page frame: header with navigation, live-mode toggle and theme toggle.
import { NavLink, Outlet } from "react-router-dom";
import { LIVE_REFRESH_MS, useSettings } from "../settings";

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
          <nav className="flex gap-1">
            <NavItem to="/">Overview</NavItem>
            <NavItem to="/phone-check">Phone check</NavItem>
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
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Outlet />
      </main>
      <footer className="mx-auto max-w-6xl px-4 pb-8 text-xs text-stone-500">
        KeetaSense · AI insect counting for yellow sticky traps · Chip to Crop hackathon (Presidency University × ICAR-IIHR).
        Thresholds are placeholders until confirmed with IIHR.
      </footer>
    </div>
  );
}
