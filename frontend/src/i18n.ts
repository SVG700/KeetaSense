// English / Kannada texts for the dashboard (texts added in the prep round).
// The words live in locales/strings.json so the Kannada review tool can export them
// (python -m backend.kannada_review export). Kannada is machine-drafted - needs review.
import strings from "./locales/strings.json";
import { useSettings } from "./settings";

export type UiLang = "en" | "kn";
type Entry = { en: string; kn: string };
const TABLE = strings as Record<string, Entry>;

/** Text for `key` in `lang`, with {placeholders} filled from `vars`. Falls back to English, then the key. */
export function translate(lang: UiLang, key: string, vars: Record<string, string | number> = {}): string {
  const entry = TABLE[key];
  let text = entry ? entry[lang] || entry.en : key;
  for (const [k, v] of Object.entries(vars)) text = text.replaceAll(`{${k}}`, String(v));
  return text;
}

/** Hook: const t = useT();  t("quality.BAD") */
export function useT() {
  const { uiLang } = useSettings();
  return (key: string, vars?: Record<string, string | number>) => translate(uiLang, key, vars);
}
