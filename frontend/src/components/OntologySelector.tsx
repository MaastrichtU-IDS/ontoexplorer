import { useOntologies } from '../hooks/useOntologies'

interface Props {
  value: string | null
  onChange: (id: string | null) => void
  required?: boolean
  placeholder?: string
}

export default function OntologySelector({ value, onChange, required, placeholder }: Props) {
  const { ontologies, isLoading } = useOntologies()

  return (
    <select
      value={value ?? ''}
      onChange={e => onChange(e.target.value || null)}
      disabled={isLoading}
      style={{
        background: 'var(--bg-secondary)',
        border: '1px solid var(--border)',
        color: value ? 'var(--text)' : 'var(--text-dim)',
        borderRadius: 'var(--radius-sm)',
        padding: '5px 8px',
        fontSize: 'var(--font-size-sm)',
        minWidth: 120,
      }}
    >
      {!required && <option value="">All</option>}
      {required && !value && (
        <option value="" disabled>
          {placeholder ?? 'Select ontology…'}
        </option>
      )}
      {ontologies.map(o => (
        <option key={o.id} value={o.id}>
          {o.id}
        </option>
      ))}
    </select>
  )
}
