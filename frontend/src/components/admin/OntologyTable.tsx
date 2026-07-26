import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { AdminOntologyEntry, AdminVersionEntry, api, slugFromIri } from '../../lib/api'
import { usePagedTable } from '../../hooks/usePagedTable'
import { TablePager } from '../TablePager'
import {
  ActionButton,
  CopyableIri,
  DiffStatusBadge,
  StatusDot,
  UpdateState,
  diffActionLabelFor,
  fmtAge,
  fmtTriples,
  ontologyDisplayName,
} from './shared'

const REASONING_ORDER: Record<string, number> = { not_started: 0, running: 1, ready: 2 }

type SortCol = 'ontology' | 'triples' | 'ingestion' | 'indexed' | 'embeddings' | 'reasoning' | 'updated'

export interface OntologyTableProps {
  rows: AdminOntologyEntry[]
  updateStates: Record<string, UpdateState>
  onUpdate: (id: string) => void
  reindexStates: Record<string, UpdateState>
  onReindex: (id: string) => void
  embedStates: Record<string, UpdateState>
  onEmbed: (id: string) => void
  reasonStates: Record<string, UpdateState>
  onReason: (id: string) => void
  profileStates: Record<string, UpdateState>
  onDetectProfile: (id: string) => void
  versionProfileStates: Record<string, UpdateState>
  onVersionDetectProfile: (versionId: string) => void
  recomputeStates: Record<string, UpdateState>
  onRecomputeAll: (ontologyId: string) => void
  pairDiffStates: Record<string, UpdateState>
  onPairDiff: (fromVid: string, toVid: string) => void
  versionIndexStates: Record<string, UpdateState>
  onVersionIndex: (versionId: string) => void
  versionEmbedStates: Record<string, UpdateState>
  onVersionEmbed: (versionId: string) => void
  versionReasonStates: Record<string, UpdateState>
  onVersionReason: (versionId: string) => void
  versionIngestStates: Record<string, UpdateState>
  onVersionIngest: (versionId: string) => void
}

export function OntologyTable({
  rows,
  updateStates, onUpdate,
  reindexStates, onReindex,
  embedStates, onEmbed,
  reasonStates, onReason,
  profileStates, onDetectProfile,
  versionProfileStates, onVersionDetectProfile,
  recomputeStates, onRecomputeAll,
  pairDiffStates, onPairDiff,
  versionIndexStates, onVersionIndex,
  versionEmbedStates, onVersionEmbed,
  versionReasonStates, onVersionReason,
  versionIngestStates, onVersionIngest,
}: OntologyTableProps) {
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<{ col: SortCol; dir: 'asc' | 'desc' }>({ col: 'ontology', dir: 'asc' })
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  function toggleExpanded(ontologyId: string) {
    setExpanded(s => {
      const n = new Set(s)
      if (n.has(ontologyId)) n.delete(ontologyId)
      else n.add(ontologyId)
      return n
    })
  }

  function toggleSort(col: SortCol) {
    setSort(s => s.col === col ? { col, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { col, dir: 'asc' })
    setPage(0)
  }

  function handleSearch(q: string) {
    setSearch(q)
    setPage(0)
  }

  const filtered = rows.filter(r => {
    if (!search) return true
    const q = search.toLowerCase()
    return (
      ontologyDisplayName(r).toLowerCase().includes(q) ||
      r.iri.toLowerCase().includes(q) ||
      (r.label ?? '').toLowerCase().includes(q) ||
      (r.shortname ?? '').toLowerCase().includes(q)
    )
  })

  const sorted = [...filtered].sort((a, b) => {
    let cmp = 0
    switch (sort.col) {
      case 'ontology':   cmp = ontologyDisplayName(a).localeCompare(ontologyDisplayName(b)); break
      case 'triples':    cmp = (a.triple_count ?? -1) - (b.triple_count ?? -1); break
      case 'ingestion':  cmp = a.ingestion_status.localeCompare(b.ingestion_status); break
      case 'indexed':    cmp = (a.indexed ? 1 : 0) - (b.indexed ? 1 : 0); break
      case 'embeddings': cmp = a.embed_count - b.embed_count; break
      case 'reasoning':  cmp = (REASONING_ORDER[a.reasoning_status] ?? 0) - (REASONING_ORDER[b.reasoning_status] ?? 0); break
      case 'updated':    cmp = (a.version_created_at ?? '').localeCompare(b.version_created_at ?? ''); break
    }
    return sort.dir === 'asc' ? cmp : -cmp
  })

  const { paged, page, setPage, pageSize, setPageSize, total } = usePagedTable(sorted, 'ontologies')

  const thBase: React.CSSProperties = {
    padding: '7px 10px', fontWeight: 500, fontSize: 10,
    textTransform: 'uppercase', letterSpacing: .5,
    cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap',
  }

  function SortTh({ col, label, align = 'center' }: { col: SortCol; label: string; align?: React.CSSProperties['textAlign'] }) {
    const active = sort.col === col
    return (
      <th onClick={() => toggleSort(col)} style={{ ...thBase, textAlign: align, color: active ? 'var(--text)' : 'var(--text-dim)' }}>
        {label} <span style={{ opacity: active ? 1 : 0.25 }}>{active && sort.dir === 'desc' ? '▼' : '▲'}</span>
      </th>
    )
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
        <input
          value={search}
          onChange={e => handleSearch(e.target.value)}
          placeholder="Search ontologies…"
          style={{
            background: 'var(--bg-secondary)', border: '1px solid var(--border)',
            borderRadius: 6, padding: '5px 10px', color: 'var(--text)',
            fontSize: 12, outline: 'none', width: 'min(240px, 100%)',
          }}
        />
        <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
          {filtered.length !== rows.length ? `${filtered.length} of ${rows.length}` : `${rows.length} total`}
        </span>
      </div>

      <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, overflowX: 'auto' }}>
        <table style={{ width: '100%', minWidth: 900, borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg)' }}>
              <th style={{ width: 28 }} />
              <SortTh col="ontology"   label="Ontology"    align="left" />
              <SortTh col="triples"    label="Triples" />
              <SortTh col="ingestion"  label="Ingestion" />
              <SortTh col="indexed"    label="Indexed" />
              <SortTh col="embeddings" label="Embeddings" />
              <SortTh col="reasoning"  label="Reasoning" />
              <th style={{ padding: '7px 10px', textAlign: 'center', color: 'var(--text-dim)', fontWeight: 500, fontSize: 10, textTransform: 'uppercase', letterSpacing: .5 }}>
                Profile
              </th>
              <th style={{ padding: '7px 10px', textAlign: 'center', color: 'var(--text-dim)', fontWeight: 500, fontSize: 10, textTransform: 'uppercase', letterSpacing: .5 }}>
                Diff
              </th>
              <SortTh col="updated"    label="Updated" />
            </tr>
          </thead>
          <tbody>
            {paged.map(row => {
              const canAct = row.ingestion_status !== 'deprecated' && row.ingestion_status !== 'pending'
              const ingestMethod = row.source_url ? 'url' : 'iri'
              return (
                <React.Fragment key={row.version_id}>
                <tr style={{ borderBottom: '1px solid var(--overlay)' }}>
                  {row.version_count > 1 ? (
                    <td style={{ padding: '6px 4px 6px 10px', textAlign: 'center', cursor: 'pointer', color: 'var(--text-dim)' }}
                        onClick={() => toggleExpanded(row.id)}>
                      {expanded.has(row.id) ? '▾' : '▸'}
                    </td>
                  ) : (
                    <td />
                  )}
                  <td style={{ padding: '6px 10px', color: 'var(--text)' }}>
                    <div>
                      <Link
                        to={`/ontologies/${row.shortname ?? slugFromIri(row.iri)}`}
                        style={{ color: 'var(--text)', textDecoration: 'none' }}
                      >
                        {ontologyDisplayName(row)}
                      </Link>
                    </div>
                    {row.label && row.label !== ontologyDisplayName(row) && (
                      <div style={{ color: 'var(--text-dim)', fontSize: 10 }}>{row.label}</div>
                    )}
                    <div style={{ display: 'flex', gap: 4, marginTop: 2, flexWrap: 'wrap' }}>
                      <CopyableIri iri={row.iri} label="IRI" />
                      {row.version_iri && <CopyableIri iri={row.version_iri} label="vIRI" />}
                    </div>
                  </td>
                  <td style={{ padding: '6px 10px', textAlign: 'center', color: 'var(--text-muted)' }}>
                    {fmtTriples(row.triple_count)}
                  </td>
                  <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                      <StatusDot status={row.ingestion_status} />
                      {(row.source_url || row.iri) && (
                        <ActionButton
                          label={`↑ ${ingestMethod}`}
                          title={row.source_url ? `Re-ingest via URL: ${row.source_url}` : `Re-ingest via IRI: ${row.iri}`}
                          state={updateStates[row.id] ?? 'idle'}
                          onClick={() => onUpdate(row.id)}
                        />
                      )}
                    </div>
                  </td>
                  <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                      <StatusDot status={row.indexed ? 'done' : 'not_started'} label={row.indexed ? 'yes' : 'no'} />
                      {canAct && (
                        <ActionButton
                          label="↺ index"
                          title="Re-index search (updates deprecated term filter, labels, synonyms)"
                          state={reindexStates[row.id] ?? 'idle'}
                          onClick={() => onReindex(row.id)}
                        />
                      )}
                    </div>
                  </td>
                  <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                      <span style={{ color: row.embed_count > 0 ? 'var(--green)' : 'var(--text-dim)', fontSize: 11 }}>
                        {row.embed_count > 0 ? fmtTriples(row.embed_count) : '—'}
                      </span>
                      {canAct && (
                        <ActionButton
                          label="⬡ embed"
                          title="Generate vector embeddings for semantic search"
                          state={embedStates[row.id] ?? 'idle'}
                          onClick={() => onEmbed(row.id)}
                        />
                      )}
                    </div>
                  </td>
                  <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                      <StatusDot status={row.reasoning_status} label={row.reasoning_status.replace('_', ' ')} />
                      {canAct && (
                        <ActionButton
                          label="⚙ reason"
                          title="Run classification"
                          state={reasonStates[row.id] ?? 'idle'}
                          onClick={() => onReason(row.id)}
                        />
                      )}
                    </div>
                  </td>
                  <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                      {row.profile_computed
                        ? <span style={{ color: 'var(--green)', fontSize: 11 }}>●</span>
                        : <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>—</span>}
                      {canAct && (
                        <ActionButton
                          label="↺ profile"
                          title="Run OWL 2 profile detection (EL/QL/RL/DL)"
                          state={profileStates[row.id] ?? 'idle'}
                          onClick={() => onDetectProfile(row.id)}
                        />
                      )}
                    </div>
                  </td>
                  <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                    <ActionButton
                      label="↺ diffs"
                      title="Queue compute_diff for every consecutive version pair of this ontology"
                      state={recomputeStates[row.id] ?? 'idle'}
                      onClick={() => onRecomputeAll(row.id)}
                    />
                  </td>
                  <td style={{ padding: '6px 10px', textAlign: 'center', color: 'var(--text-dim)', fontSize: 11 }}>
                    {fmtAge(row.version_created_at)}
                  </td>
                </tr>
                {expanded.has(row.id) && (
                  <VersionsSubRows
                    ontologyId={row.id}
                    slug={row.shortname ?? slugFromIri(row.iri)}
                    colSpan={10}
                    latestVersionId={row.version_id}
                    currentVersionId={row.current_version_id}
                    pairDiffStates={pairDiffStates}
                    onPairDiff={onPairDiff}
                    versionIndexStates={versionIndexStates}
                    onVersionIndex={onVersionIndex}
                    versionEmbedStates={versionEmbedStates}
                    onVersionEmbed={onVersionEmbed}
                    versionReasonStates={versionReasonStates}
                    onVersionReason={onVersionReason}
                    versionProfileStates={versionProfileStates}
                    onVersionDetectProfile={onVersionDetectProfile}
                    versionIngestStates={versionIngestStates}
                    onVersionIngest={onVersionIngest}
                  />
                )}
                </React.Fragment>
              )
            })}
            {paged.length === 0 && (
              <tr>
                <td colSpan={10} style={{ padding: '16px', textAlign: 'center', color: 'var(--text-dim)' }}>
                  {search ? 'No matching ontologies' : 'No ontologies'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <TablePager total={total} page={page} pageSize={pageSize} onPage={setPage} onPageSize={setPageSize} />
    </div>
  )
}

// ── Version sub-rows (lazy fetch when a parent row is expanded) ───────────────

interface VersionsSubRowsProps {
  ontologyId: string
  slug: string
  colSpan: number
  latestVersionId: string
  currentVersionId: string | null
  pairDiffStates: Record<string, UpdateState>
  onPairDiff: (fromVid: string, toVid: string) => void
  versionIndexStates: Record<string, UpdateState>
  onVersionIndex: (versionId: string) => void
  versionEmbedStates: Record<string, UpdateState>
  onVersionEmbed: (versionId: string) => void
  versionReasonStates: Record<string, UpdateState>
  onVersionReason: (versionId: string) => void
  versionProfileStates: Record<string, UpdateState>
  onVersionDetectProfile: (versionId: string) => void
  versionIngestStates: Record<string, UpdateState>
  onVersionIngest: (versionId: string) => void
}

function VersionsSubRows({
  ontologyId, slug, colSpan, latestVersionId, currentVersionId,
  pairDiffStates, onPairDiff,
  versionIndexStates, onVersionIndex,
  versionEmbedStates, onVersionEmbed,
  versionReasonStates, onVersionReason,
  versionProfileStates, onVersionDetectProfile,
  versionIngestStates, onVersionIngest,
}: VersionsSubRowsProps) {
  const qc = useQueryClient()
  const { data, isLoading, isError } = useQuery({
    queryKey: ['admin-versions', ontologyId],
    queryFn: () => api.admin.versions(ontologyId),
    refetchInterval: 10_000,
  })

  const setDefault = useMutation({
    mutationFn: (cvid: string | null) => api.ontologies.patch(ontologyId, { current_version_id: cvid }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-versions', ontologyId] })
      qc.invalidateQueries({ queryKey: ['admin', 'overview'] })
      qc.invalidateQueries({ queryKey: ['ontologies'] })
    },
  })

  if (isLoading) {
    return (
      <tr>
        <td colSpan={colSpan} style={{ padding: '8px 16px', color: 'var(--text-dim)', fontSize: 11 }}>
          Loading versions…
        </td>
      </tr>
    )
  }
  if (isError || !data) {
    return (
      <tr>
        <td colSpan={colSpan} style={{ padding: '8px 16px', color: 'var(--red)', fontSize: 11 }}>
          Failed to load versions
        </td>
      </tr>
    )
  }

  const others: AdminVersionEntry[] = data.versions.filter(v => v.version_id !== latestVersionId)

  const vlabel = (v: AdminVersionEntry): string => {
    const seg = v.version_iri ? (v.version_iri.replace(/[/#]+$/, '').split(/[/#]/).pop() ?? v.version_iri) : ''
    // Prefer a clean version/date token (e.g. "0.2.14", "2024-05-01") over the
    // filename; fall back to the filename, then the version-id prefix.
    const m = seg.match(/\d{4}-\d{2}-\d{2}/) ?? seg.match(/\d+(?:\.\d+)+/)
    return m ? m[0] : (seg || v.version_id.slice(0, 8))
  }
  const readyVersions = data.versions.filter(
    v => !['deprecated', 'pending', 'failed'].includes(v.ingestion_status))
  const currentDefault = readyVersions.find(v => v.version_id === latestVersionId) ?? readyVersions[0]

  // "Default version" picker — pin a specific version or return to automatic
  // (version-aware) selection. Same PATCH the dashboard uses.
  const defaultRow = readyVersions.length > 1 ? (
    <tr key="__default_picker" style={{ background: 'rgba(88,166,255,0.06)' }}>
      <td />
      <td colSpan={colSpan - 1} style={{ padding: '8px 10px', fontSize: 11 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ color: 'var(--text-dim)' }}>Default version:</span>
          <select
            value={currentVersionId ?? ''}
            onChange={e => setDefault.mutate(e.target.value || null)}
            disabled={setDefault.isPending}
            style={{ fontSize: 11, background: 'var(--bg-secondary)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 4, padding: '2px 6px' }}
          >
            <option value="">Automatic (latest by version)</option>
            {readyVersions.map(v => <option key={v.version_id} value={v.version_id}>{vlabel(v)}</option>)}
          </select>
          <span style={{ color: 'var(--text-dim)' }}>
            {currentVersionId ? 'pinned' : 'auto'}{currentDefault ? ` · currently ${vlabel(currentDefault)}` : ''}
          </span>
        </div>
      </td>
    </tr>
  ) : null

  if (others.length === 0) {
    return (
      <>
        {defaultRow}
        <tr>
          <td colSpan={colSpan} style={{ padding: '8px 16px', color: 'var(--text-dim)', fontSize: 11 }}>
            No older versions
          </td>
        </tr>
      </>
    )
  }

  return (
    <>
      {defaultRow}
      {others.map(v => (
        <tr key={v.version_id} style={{ background: 'var(--overlay)' }}>
          <td />
          <td style={{ padding: '6px 10px', color: 'var(--text-muted)', fontSize: 11 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              <Link
                to={`/ontologies/${slug}/${v.version_id}`}
                style={{ color: 'var(--text-muted)', textDecoration: 'none', fontFamily: 'monospace' }}
                title={`version ${v.version_id}`}
              >
                ↳ {vlabel(v)}
              </Link>
              {v.version_iri && <CopyableIri iri={v.version_iri} label="vIRI" />}
              {v.ingestion_status === 'deprecated' && (
                <span style={{ color: 'var(--red)' }}>● deprecated</span>
              )}
            </div>
          </td>
          <td style={{ padding: '6px 10px', textAlign: 'center', color: 'var(--text-muted)' }}>
            {fmtTriples(v.triple_count)}
          </td>
          <td style={{ padding: '6px 10px', textAlign: 'center' }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
              <StatusDot status={v.ingestion_status} />
              <ActionButton
                label={v.source_url ? '↑ url' : '↑ iri'}
                title={v.source_url
                  ? `Re-fetch ${v.source_url} — creates a new version if bytes changed`
                  : `Re-fetch the ontology IRI — creates a new version if bytes changed`}
                state={versionIngestStates[v.version_id] ?? 'idle'}
                onClick={() => onVersionIngest(v.version_id)}
              />
            </div>
          </td>
          <td style={{ padding: '6px 10px', textAlign: 'center' }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
              <StatusDot status={v.indexed ? 'done' : 'not_started'} label={v.indexed ? 'yes' : 'no'} />
              <ActionButton
                label="↺ index"
                title="Re-index search for this specific version"
                state={versionIndexStates[v.version_id] ?? 'idle'}
                onClick={() => onVersionIndex(v.version_id)}
              />
            </div>
          </td>
          <td style={{ padding: '6px 10px', textAlign: 'center' }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
              <span style={{ color: v.embed_count > 0 ? 'var(--green)' : 'var(--text-dim)', fontSize: 11 }}>
                {v.embed_count > 0 ? fmtTriples(v.embed_count) : '—'}
              </span>
              <ActionButton
                label="⬡ embed"
                title="Generate embeddings for this specific version"
                state={versionEmbedStates[v.version_id] ?? 'idle'}
                onClick={() => onVersionEmbed(v.version_id)}
              />
            </div>
          </td>
          <td style={{ padding: '6px 10px', textAlign: 'center' }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
              <StatusDot status={v.reasoning_status} label={v.reasoning_status.replace('_', ' ')} />
              <ActionButton
                label="⚙ reason"
                title="Run OWL-EL classification for this specific version"
                state={versionReasonStates[v.version_id] ?? 'idle'}
                onClick={() => onVersionReason(v.version_id)}
              />
            </div>
          </td>
          <td style={{ padding: '6px 10px', textAlign: 'center' }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
              {v.profile_computed
                ? <span style={{ color: 'var(--green)', fontSize: 11 }}>●</span>
                : <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>—</span>}
              <ActionButton
                label="↺ profile"
                title="Run OWL 2 profile detection for this specific version"
                state={versionProfileStates[v.version_id] ?? 'idle'}
                onClick={() => onVersionDetectProfile(v.version_id)}
              />
            </div>
          </td>
          <td style={{ padding: '6px 10px', textAlign: 'center' }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
              <DiffStatusBadge status={v.diff_vs_prev.status} />
              {v.diff_vs_prev.previous_version_id && (
                <ActionButton
                  label={diffActionLabelFor(v.diff_vs_prev.status)}
                  title={`Queue compute_diff against ${v.diff_vs_prev.previous_version_id.slice(0, 8)}…`}
                  state={pairDiffStates[`${v.diff_vs_prev.previous_version_id}->${v.version_id}`] ?? 'idle'}
                  onClick={() => onPairDiff(v.diff_vs_prev.previous_version_id!, v.version_id)}
                />
              )}
            </div>
          </td>
          <td style={{ padding: '6px 10px', textAlign: 'center', color: 'var(--text-dim)', fontSize: 11 }}>
            {fmtAge(v.version_created_at)}
          </td>
        </tr>
      ))}
    </>
  )
}
