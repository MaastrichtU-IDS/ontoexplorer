export default function ResolvableBadge({ resolvable, checkedAt }: {
  resolvable?: boolean | null
  checkedAt?: string | null
}) {
  if (resolvable !== true) return null  // only a positive signal is shown
  const when = checkedAt ? new Date(checkedAt).toLocaleDateString() : ''
  return (
    <span
      title={`This ontology's IRI dereferences to RDF via content negotiation${when ? ` (checked ${when})` : ''}.`}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 4, padding: '1px 8px',
        borderRadius: 10, fontSize: 11, fontWeight: 600,
        background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-muted)',
        whiteSpace: 'nowrap',
      }}
    >
      🔗 Resolvable
    </span>
  )
}
