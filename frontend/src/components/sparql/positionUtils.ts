export type Position =
  | { kind: 'none' }
  | { kind: 'iri'; partial: string }
  | { kind: 'curie'; partial: string; prefix: string; baseIri?: string }

interface MinimalToken {
  string: string
  type: string | null
}

/**
 * Classify what kind of completion is appropriate at the cursor token.
 *
 * - `iri`   : cursor is inside `<...>`. Suggest matching IRIs.
 * - `curie` : cursor is in a `prefix:local` token. Suggest local names.
 * - `none`  : variable, literal, keyword, empty — no suggestions.
 *
 * @param token         { string, type } from yasqe.getCompleteToken() / getTokenAt()
 * @param queryPrefixes prefix-name → base-iri map (from yasqe.getPrefixesFromQuery())
 */
export function classifyPosition(token: MinimalToken, queryPrefixes: Record<string, string>): Position {
  const s = token.string
  if (!s) return { kind: 'none' }
  if (s.startsWith('?') || s.startsWith('$')) return { kind: 'none' }
  if (token.type === 'string') return { kind: 'none' }
  if (token.type === 'keyword') return { kind: 'none' }

  if (s.startsWith('<')) {
    return { kind: 'iri', partial: s.slice(1) }
  }

  const colonIdx = s.indexOf(':')
  if (colonIdx > 0) {
    const prefix = s.slice(0, colonIdx)
    const partial = s.slice(colonIdx + 1)
    const baseIri = queryPrefixes[prefix]
    return baseIri
      ? { kind: 'curie', partial, prefix, baseIri }
      : { kind: 'curie', partial, prefix }
  }

  return { kind: 'none' }
}
