/** Colored badge showing which other ontology a term originates from — either
 *  formally imported (owl:imports) or reused by direct external IRI reference. */

function sourceHue(name: string): number {
  let h = 5381
  for (let i = 0; i < name.length; i++) h = (((h << 5) + h) ^ name.charCodeAt(i)) >>> 0
  return h % 360
}

export default function SourceBadge({ source, style }: { source: string; style?: React.CSSProperties }) {
  if (!source) return null
  const hue = sourceHue(source)
  return (
    <span
      title={`From ontology: ${source} (imported or reused)`}
      style={{
        fontSize: 9, fontWeight: 700, letterSpacing: 0.4,
        background: `hsl(${hue}, 45%, 18%)`,
        color: `hsl(${hue}, 75%, 68%)`,
        border: `1px solid hsl(${hue}, 40%, 30%)`,
        borderRadius: 3, padding: '1px 4px',
        flexShrink: 0, userSelect: 'none',
        ...style,
      }}
    >
      {source}
    </span>
  )
}
