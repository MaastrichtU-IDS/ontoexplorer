import { useInfiniteQuery } from '@tanstack/react-query'
import { useState, useEffect } from 'react'
import { api, Ontology, ProfileName, LanguageTier } from '../lib/api'

const PAGE_SIZE = 50

function useDebounce<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return debounced
}

/**
 * Infinite (offset-paged) ontology list for the /ontologies table. The server
 * is authoritative for sort + every filter (including the language-code facet),
 * so the page fetches one PAGE_SIZE window to paint and loads more on scroll —
 * first paint is constant-time regardless of catalogue size. `view=list` keeps
 * each row lean. (The picker keeps using the single-shot useOntologySearch.)
 */
export function useOntologiesInfinite(opts: {
  query: string
  group?: string
  profile?: ProfileName
  reuses?: string
  language?: LanguageTier   // expressivity tier (rdf | rdfs | rdfs-plus | owl)
  langs: string[]           // BCP-47 language codes from the facet chips
  sort: 'name' | 'date'
  dir: 'asc' | 'desc'
}) {
  const { group, profile, reuses, language, langs, sort, dir } = opts
  const q = useDebounce(opts.query.trim(), 250)
  const langKey = [...langs].sort().join(',')

  const query = useInfiniteQuery({
    queryKey: ['ontologies', 'infinite', q, group ?? '', profile ?? '', reuses ?? '', language ?? '', langKey, sort, dir],
    queryFn: ({ pageParam }) =>
      api.ontologies.list(
        pageParam as number, PAGE_SIZE,
        q || undefined, group || undefined, profile, reuses, false, language, 'list',
        { sort, dir, langs },
      ),
    // Prefer the server `total` to know when to stop; fall back to short-page
    // detection (a page shorter than PAGE_SIZE is the last one).
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.ontologies.length, 0)
      if (typeof last.total === 'number') return loaded < last.total ? loaded : undefined
      return last.ontologies.length === PAGE_SIZE ? loaded : undefined
    },
    initialPageParam: 0,
    staleTime: 30_000,
  })

  const ontologies: Ontology[] = query.data?.pages.flatMap(p => p.ontologies) ?? []
  const total = query.data?.pages[0]?.total
  return { ...query, ontologies, total }
}
