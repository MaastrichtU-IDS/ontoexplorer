interface Props {
  frame: string
}

/**
 * Renders a Protégé-style Manchester OWL frame as a monospace block.
 * Lines starting with `-` are red (removed); `+` are green (added);
 * everything else is the default text color (header / keyword lines).
 */
export default function ManchesterFrame({ frame }: Props) {
  return (
    <pre
      style={{
        margin: 0,
        padding: '0.5rem 0.75rem',
        background: 'var(--bg-secondary)',
        border: '1px solid var(--border)',
        borderRadius: 4,
        fontFamily: 'var(--font-mono, ui-monospace, monospace)',
        fontSize: 12,
        lineHeight: 1.45,
        whiteSpace: 'pre',
        overflowX: 'auto',
      }}
    >
      {frame.split('\n').map((line, i) => {
        const color =
          line.startsWith('-') ? '#f85149' :
          line.startsWith('+') ? '#3fb950' :
          'var(--text)'
        return (
          <div key={i} style={{ color }}>{line}</div>
        )
      })}
    </pre>
  )
}
