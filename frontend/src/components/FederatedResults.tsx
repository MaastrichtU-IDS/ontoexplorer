import type { FederatedBlock } from '../lib/api'

// "Also found in other catalogues": remote MOD-API rows, kept structurally
// separate from the local (navigable) catalogue. Each row links OUT to the
// remote catalogue's landing page in a new tab.
export default function FederatedResults({ federated }: { federated?: FederatedBlock }) {
  if (!federated) return null
  const { catalogues, results } = federated
  const responded = catalogues.filter(c => c.status !== 'timeout' && c.status !== 'error').length
  const failed = catalogues.filter(c => c.status === 'timeout' || c.status === 'error')

  return (
    <section style={{ marginTop: '1.25rem' }} aria-label="Federated results">
      <h3 style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', margin: '0 0 4px' }}>
        Also found in other catalogues
      </h3>
      <p style={{ color: 'var(--text-dim)', fontSize: 12, margin: '0 0 8px' }}>
        {responded} of {catalogues.length} catalogues responded
        {failed.length > 0 && (
          <> ({failed.map(c => `${c.label}: ${c.status}`).join(', ')})</>
        )}
      </p>
      {results.length === 0 ? (
        <p style={{ color: 'var(--text-dim)', fontSize: 13 }}>No additional matches in other catalogues.</p>
      ) : (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 2 }}>
          {results.map(r => {
            const name = r.title?.trim() || r.acronym || r.iri
            const row = (
              <>
                <span style={{
                  fontWeight: 600, flexShrink: 1, minWidth: 0,
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>{name}</span>
                {r.acronym && (
                  <span style={{
                    color: 'var(--text-muted)', fontSize: 12, flexShrink: 0,
                    fontFamily: 'var(--font-mono, ui-monospace, monospace)',
                  }}>{r.acronym}</span>
                )}
                <span style={{
                  marginLeft: 'auto', fontSize: 10, background: 'var(--bg)', color: 'var(--accent)',
                  borderRadius: 3, padding: '1px 5px', textTransform: 'uppercase', flexShrink: 0,
                }}>{r.source.label}</span>
              </>
            )
            const style: React.CSSProperties = {
              display: 'flex', alignItems: 'baseline', gap: 8, padding: '8px 12px',
              borderRadius: 'var(--radius)', textDecoration: 'none', color: 'var(--text)',
              border: '1px dashed var(--border)', background: 'var(--bg-secondary)',
            }
            return (
              <li key={`${r.source.id}:${r.iri}`}>
                {r.source_landing_url ? (
                  <a href={r.source_landing_url} target="_blank" rel="noopener noreferrer" style={style}>
                    {row}
                  </a>
                ) : (
                  <div style={style}>{row}</div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
