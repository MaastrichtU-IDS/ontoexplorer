import { useSyncExternalStore } from 'react'
import { getTheme, setTheme, subscribe, toggleTheme } from '../lib/theme'

/**
 * Active theme id plus controls, backed by the shared store in lib/theme so
 * every consumer (NavBar toggle, Profile picker) stays in sync.
 *
 * - `toggle` is the nav button: always lands on one of the two default themes
 *   (light ⇄ dark) based on the current mode, whatever palette is active.
 * - `setTheme` is the Profile picker: applies any theme by id.
 *
 * Both persist the choice.
 */
export function useTheme(): {
  theme: string
  setTheme: (id: string) => void
  toggle: () => void
} {
  const theme = useSyncExternalStore(subscribe, getTheme, getTheme)
  return { theme, setTheme, toggle: toggleTheme }
}
