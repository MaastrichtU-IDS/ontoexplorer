import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import Yasgui from '@triply/yasgui'
import '@triply/yasgui/build/yasgui.min.css'
import './Sparql.css'
import QuerySidebar from '../components/QuerySidebar'
import { api } from '../lib/api'
import { useOntologies } from '../hooks/useOntologies'
import type { Ontology } from '../lib/api'

const DEFAULT_QUERY = `PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

# All triples are stored in named graphs (one per ontology version).
# Use GRAPH ?g { ... } to query across all ontologies, or bind ?g to
# a specific graph IRI to query a single ontology version.

SELECT ?class ?label WHERE {
  GRAPH ?g {
    ?class a owl:Class .
    OPTIONAL { ?class rdfs:label ?label }
  }
}
LIMIT 100`

// ── Helpers ──────────────────────────────────────────────────────────────────

function iriSlug(iri: string): string {
  return (
    iri.replace(/[/#]+$/, '').split(/[/#]/).pop()
      ?.replace(/\.(owl|ttl|rdf|obo|json|xml|nt)$/i, '') ?? iri
  )
}

interface GraphEntry { name: string; graphUri: string }

function toEntries(ontologies: Ontology[]): GraphEntry[] {
  return ontologies
    .filter(o =>
      o.latest_version &&
      !['pending', 'failed', 'deprecated'].includes(o.latest_version.status)
    )
    .map(o => ({
      name: o.shortname ?? iriSlug(o.iri),
      graphUri: `urn:ontology:${o.id}:${o.latest_version!.id}`,
    }))
}

// ── GraphsPanel ───────────────────────────────────────────────────────────────

function GraphsPanel({ entries }: { entries: GraphEntry[] }) {
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState('')
  const [copied, setCopied] = useState<string | null>(null)

  const q = filter.trim().toLowerCase()
  const visible = q
    ? entries.filter(e =>
        e.name.toLowerCase().includes(q) || e.graphUri.toLowerCase().includes(q)
      )
    : entries

  function copyUri(uri: string) {
    navigator.clipboard.writeText(uri).then(() => {
      setCopied(uri)
      setTimeout(() => setCopied(null), 1500)
    }).catch(() => {})
  }

  return (
    <div style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg-secondary)', flexShrink: 0 }}>
      <div style={{
        padding: '0 1.5rem', height: 32,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <button
          onClick={() => setOpen(v => !v)}
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', padding: 0,
          }}
        >
          Graphs ({entries.length}) {open ? '▴' : '▾'}
        </button>
        {!open && (
          <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)' }}>
            browse named graph URIs for GRAPH / FROM NAMED clauses
          </span>
        )}
      </div>
      {open && (
        <div style={{ padding: '0 1.5rem 0.75rem' }}>
          <input
            value={filter}
            onChange={e => setFilter(e.target.value)}
            placeholder="Filter ontologies…"
            style={{
              width: '100%', boxSizing: 'border-box',
              padding: '4px 8px', fontSize: 12,
              background: 'var(--bg)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)', color: 'var(--text)',
              outline: 'none', marginBottom: 6,
            }}
          />
          <div style={{ maxHeight: 220, overflowY: 'auto' }}>
            {visible.length === 0 ? (
              <div style={{ textAlign: 'center', color: 'var(--text-dim)', fontSize: 12, padding: '8px 0' }}>
                No matching ontologies
              </div>
            ) : (
              visible.map(e => (
                <div key={e.graphUri} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '3px 0' }}>
                  <span style={{ fontSize: 12, color: 'var(--text)', flexShrink: 0, minWidth: 80 }}>
                    {e.name}
                  </span>
                  <span style={{
                    fontSize: 11, color: 'var(--text-dim)', fontFamily: 'monospace',
                    flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {e.graphUri}
                  </span>
                  <button
                    onClick={() => copyUri(e.graphUri)}
                    style={{
                      background: 'none', border: '1px solid var(--border)',
                      borderRadius: 3, padding: '1px 7px', fontSize: 11,
                      color: copied === e.graphUri ? 'var(--accent-green, #3fb950)' : 'var(--text-dim)',
                      cursor: 'pointer', flexShrink: 0,
                    }}
                  >
                    {copied === e.graphUri ? '✓' : 'Copy'}
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Sparql() {
  const containerRef = useRef<HTMLDivElement>(null)
  const yasguiRef = useRef<InstanceType<typeof Yasgui> | null>(null)
  const namedGraphsRef = useRef<string[]>([])
  const location = useLocation()
  const [queryError, setQueryError] = useState<string | null>(null)
  const { ontologies } = useOntologies()

  const entries = useMemo(() => toEntries(ontologies), [ontologies])

  useEffect(() => {
    namedGraphsRef.current = entries.map(e => e.graphUri)
  }, [entries])

  useEffect(() => {
    if (!containerRef.current || yasguiRef.current) return

    yasguiRef.current = new Yasgui(containerRef.current, {
      persistenceId: null,
      yasqe: {
        namedGraphs: () => namedGraphsRef.current,
      },
      requestConfig: {
        endpoint: '/api/v1/sparql/content',
        method: 'POST',
        acceptHeaderSelect: 'application/sparql-results+json',
        acceptHeaderGraph: 'text/turtle',
      },
      endpointCatalogueOptions: {
        getData: () => [
          { endpoint: '/api/v1/sparql/content', title: 'OntoExplorer — Ontology Content' },
        ],
      },
    } as any)

    const qId = new URLSearchParams(location.search).get('q')
    if (qId) {
      api.savedQueries.get(qId)
        .then(sq => {
          yasguiRef.current?.getTab()?.getYasqe()?.setValue(sq.query_text)
        })
        .catch(() => {
          setQueryError('Query not found or not accessible')
          yasguiRef.current?.getTab()?.getYasqe()?.setValue(DEFAULT_QUERY)
        })
    } else {
      yasguiRef.current.getTab()?.getYasqe()?.setValue(DEFAULT_QUERY)
    }

    return () => {
      if (yasguiRef.current) {
        if (typeof yasguiRef.current.destroy === 'function') {
          yasguiRef.current.destroy()
        } else if (containerRef.current) {
          containerRef.current.innerHTML = ''
        }
        yasguiRef.current = null
      }
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div style={{
      height: 'calc(100vh - var(--nav-height))',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
      background: 'var(--bg)',
    }}>
      <div style={{
        padding: '0.6rem 1.5rem',
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg-secondary)',
        flexShrink: 0,
        display: 'flex',
        alignItems: 'baseline',
        gap: '0.75rem',
      }}>
        <h1 style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text)' }}>SPARQL</h1>
        <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)' }}>
          Query the full ontology graph · read-only · SPARQL 1.1
        </span>
      </div>
      <GraphsPanel entries={entries} />
      {queryError && (
        <div style={{
          padding: '0.4rem 1.5rem',
          background: 'rgba(239,68,68,0.1)',
          borderBottom: '1px solid rgba(239,68,68,0.3)',
          color: '#f87171',
          fontSize: 'var(--font-size-sm)',
          flexShrink: 0,
        }}>
          {queryError}
        </div>
      )}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'row', overflow: 'hidden', minHeight: 0 }}>
        <QuerySidebar yasguiRef={yasguiRef} />
        <div ref={containerRef} style={{ flex: 1, minHeight: 0 }} />
      </div>
    </div>
  )
}
