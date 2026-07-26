import { useTheme } from '../hooks/useTheme'
import { themeMode } from '../lib/theme'

export default function ThemeToggle() {
  const { theme, toggle } = useTheme()
  const isDark = themeMode(theme) === 'dark'
  return (
    <button
      onClick={toggle}
      aria-label={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
      title={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
      style={{
        background: 'none',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        padding: '4px 9px',
        color: 'var(--text-dim)',
        fontSize: 13,
        lineHeight: 1,
        cursor: 'pointer',
      }}
    >
      {isDark ? '☀' : '☾'}
    </button>
  )
}
