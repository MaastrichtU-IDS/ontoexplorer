import { useTheme } from '../hooks/useTheme'
import { THEMES } from '../lib/theme'

/**
 * Grid of theme swatches for Profile > Appearance. Each swatch shows its own
 * palette (literal colors, not the active theme's vars) so all options preview
 * at once. Clicking applies + persists immediately via the shared store.
 */
export default function ThemePicker() {
  const { theme, setTheme } = useTheme()
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))',
      gap: 10,
    }}>
      {THEMES.map(t => {
        const active = theme === t.id
        return (
          <button
            key={t.id}
            onClick={() => setTheme(t.id)}
            aria-pressed={active}
            style={{
              display: 'flex', alignItems: 'center', gap: 9,
              padding: '8px 10px', borderRadius: 'var(--radius-sm)',
              border: '1px solid ' + (active ? 'var(--accent)' : 'var(--border)'),
              background: active ? 'var(--bg-hover)' : 'var(--bg)',
              cursor: 'pointer', textAlign: 'left',
            }}
          >
            <span
              aria-hidden
              style={{
                width: 26, height: 26, borderRadius: 6, flexShrink: 0,
                border: '1px solid var(--border)',
                background: `linear-gradient(135deg, ${t.swatch[0]} 0 55%, ${t.swatch[1]} 55% 100%)`,
              }}
            />
            <span style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
              <span style={{ fontSize: 'var(--font-size-sm)', fontWeight: 600, color: 'var(--text)' }}>
                {t.label}
              </span>
              <span style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                {t.mode}{active ? ' · active' : ''}
              </span>
            </span>
          </button>
        )
      })}
    </div>
  )
}
