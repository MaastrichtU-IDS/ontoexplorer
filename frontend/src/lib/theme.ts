// Theme resolution, persistence, and a tiny shared store.
//
// The default dark theme is the CSS :root; every other palette is a full
// override under :root[data-theme="<id>"] in index.css. We persist a single
// theme id. The nav toggle only ever flips between the two defaults
// ("dark" / "light"); the Profile picker can select any theme here.
//
// State lives in a module-level store (not component state) so the NavBar
// toggle and the Profile picker always agree — they subscribe via useTheme.

export type ThemeMode = 'light' | 'dark'

export interface ThemeDef {
  id: string
  label: string
  mode: ThemeMode
  /** Two representative swatch colors [surface, accent] for the picker. */
  swatch: [string, string]
}

// Order drives the Profile picker. DEFAULT_DARK / DEFAULT_LIGHT are the
// toggle's two targets.
export const THEMES: ThemeDef[] = [
  { id: 'dark',      label: 'Slate',     mode: 'dark',  swatch: ['#0f172a', '#22c55e'] },
  { id: 'light',     label: 'Daylight',  mode: 'light', swatch: ['#ffffff', '#16a34a'] },
  { id: 'blueprint', label: 'Blueprint', mode: 'dark',  swatch: ['#0a1929', '#4fc3f7'] },
  { id: 'arctic',    label: 'Arctic',    mode: 'light', swatch: ['#f8fafe', '#2b8dd6'] },
  { id: 'nord',      label: 'Nord',      mode: 'dark',  swatch: ['#2e3440', '#88c0d0'] },
  { id: 'terminal',  label: 'Terminal',  mode: 'dark',  swatch: ['#000000', '#33ff33'] },
]

export const DEFAULT_DARK = 'dark'
export const DEFAULT_LIGHT = 'light'

const STORAGE_KEY = 'oe-theme'

const byId = (id: string): ThemeDef | undefined => THEMES.find(t => t.id === id)

export function isTheme(id: string | null): id is string {
  return !!id && THEMES.some(t => t.id === id)
}

export function themeMode(id: string): ThemeMode {
  return byId(id)?.mode ?? 'dark'
}

/** The user's explicitly chosen theme id, or null if never set. */
export function getStoredTheme(): string | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    return isTheme(v) ? v : null
  } catch {
    return null
  }
}

function storeTheme(id: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, id)
  } catch {
    /* private mode / storage disabled — fall back to session-only theming */
  }
}

/** The default theme matching the OS preference (dark when unknown). */
export function systemTheme(): string {
  return window.matchMedia?.('(prefers-color-scheme: light)').matches
    ? DEFAULT_LIGHT
    : DEFAULT_DARK
}

/** Stored choice wins; otherwise follow the OS. */
export function resolveInitialTheme(): string {
  return getStoredTheme() ?? systemTheme()
}

function applyToDom(id: string): void {
  document.documentElement.setAttribute('data-theme', id)
}

// ---- Shared store -------------------------------------------------------

let current: string | null = null
const listeners = new Set<() => void>()

/** Current theme id; initializes lazily from storage / OS on first read. */
export function getTheme(): string {
  if (current === null) current = resolveInitialTheme()
  return current
}

export function subscribe(cb: () => void): () => void {
  listeners.add(cb)
  return () => {
    listeners.delete(cb)
  }
}

/** Set the active theme. `persist` records it as the user's explicit choice. */
export function setTheme(id: string, persist = true): void {
  current = id
  if (persist) storeTheme(id)
  applyToDom(id)
  listeners.forEach(l => l())
}

/** Toggle helper: always resolves to one of the two default themes. */
export function toggleTheme(): void {
  setTheme(themeMode(getTheme()) === 'dark' ? DEFAULT_LIGHT : DEFAULT_DARK)
}

/** Apply the resolved theme to the DOM at boot (call before first paint). */
export function initTheme(): void {
  applyToDom(getTheme())
}

// While the user hasn't pinned a choice, track the OS preference live.
if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
  const mq = window.matchMedia('(prefers-color-scheme: light)')
  mq.addEventListener?.('change', () => {
    if (!getStoredTheme()) setTheme(systemTheme(), false)
  })
}
