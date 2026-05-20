/**
 * Normalise an ontology IRI to a usable base for prefix declarations.
 * If it already ends in `/` or `#`, return as-is; otherwise append `/`.
 */
export function extractBaseIri(ontologyIri: string): string {
  if (ontologyIri.endsWith('/') || ontologyIri.endsWith('#')) return ontologyIri
  return `${ontologyIri}/`
}

/**
 * True if the query text already contains a PREFIX declaration for the given
 * shortname. Case-insensitive on the PREFIX keyword; whitespace-tolerant.
 */
export function hasPrefix(queryText: string, shortname: string): boolean {
  const escaped = shortname.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const re = new RegExp(`^\\s*PREFIX\\s+${escaped}\\s*:\\s*<`, 'im')
  return re.test(queryText)
}

/**
 * Prepend `PREFIX <shortname>: <baseIri>\n` to the query text. Does not check
 * for duplicates — callers should `hasPrefix(...)` first.
 */
export function prependPrefix(queryText: string, shortname: string, baseIri: string): string {
  return `PREFIX ${shortname}: <${baseIri}>\n${queryText}`
}
