import { useState } from 'react'
import { useOntologyMeta, useMetaCandidates, usePatchMeta, useDetectMeta } from '../hooks/useOntologyMeta'
import { OntologyMetaProfile, MetaProfilePatch } from '../lib/api'

const IRI_LABELS: Record<string, string> = {
  'http://purl.org/dc/terms/title': 'dcterms:title',
  'http://www.w3.org/2000/01/rdf-schema#label': 'rdfs:label',
  'http://purl.org/dc/elements/1.1/title': 'dc:title',
  'http://purl.org/dc/terms/alternative': 'dcterms:alternative',
  'http://www.w3.org/2002/07/owl#acronym': 'owl:acronym',
  'http://purl.org/vocab/vann/preferredNamespacePrefix': 'vann:preferredNamespacePrefix',
  'http://purl.org/dc/terms/description': 'dcterms:description',
  'http://www.w3.org/2000/01/rdf-schema#comment': 'rdfs:comment',
  'http://purl.org/dc/elements/1.1/description': 'dc:description',
  'http://purl.org/dc/terms/creator': 'dcterms:creator',
  'http://purl.org/dc/elements/1.1/creator': 'dc:creator',
  'http://purl.org/pav/authoredBy': 'pav:authoredBy',
  'http://purl.org/dc/terms/contributor': 'dcterms:contributor',
  'http://purl.org/dc/terms/publisher': 'dcterms:publisher',
  'http://purl.org/dc/terms/license': 'dcterms:license',
  'http://purl.org/dc/terms/rights': 'dcterms:rights',
  'http://xmlns.com/foaf/0.1/homepage': 'foaf:homepage',
  'http://www.w3.org/ns/dcat#accessURL': 'dcat:accessURL',
  'https://schema.org/includedInDataCatalog': 'schema:includedInDataCatalog',
  'http://www.w3.org/2002/07/owl#versionInfo': 'owl:versionInfo',
  'http://purl.org/vocab/vann/preferredNamespaceUri': 'vann:preferredNamespaceUri',
  'http://purl.org/dc/terms/created': 'dcterms:created',
  'http://purl.org/dc/terms/issued': 'dcterms:issued',
  'http://purl.org/dc/terms/modified': 'dcterms:modified',
  'http://purl.org/dc/terms/language': 'dcterms:language',
  'http://purl.org/dc/terms/bibliographicCitation': 'dcterms:bibliographicCitation',
  'https://schema.org/funding': 'schema:funding',
  'https://w3id.org/mod#status': 'mod:status',
  'https://w3id.org/mod#hasSyntax': 'mod:hasSyntax',
  'https://w3id.org/mod#hasRepresentationLanguage': 'mod:hasRepresentationLanguage',
  'http://www.w3.org/2002/07/owl#versionIRI': 'owl:versionIRI',
  'http://www.w3.org/2000/01/rdf-schema#seeAlso': 'rdfs:seeAlso',
  'http://www.w3.org/2000/01/rdf-schema#isDefinedBy': 'rdfs:isDefinedBy',
  'https://w3id.org/mod#competencyQuestion': 'mod:competencyQuestion',
  'https://w3id.org/mod#endorsedBy': 'mod:endorsedBy',
  'https://w3id.org/mod#reliesOn': 'mod:reliesOn',
  'https://w3id.org/mod#similar': 'mod:similar',
  'https://w3id.org/mod#generalizes': 'mod:generalizes',
  'https://w3id.org/mod#specializes': 'mod:specializes',
  'https://w3id.org/mod#knownUsage': 'mod:knownUsage',
  'https://w3id.org/mod#usedInProject': 'mod:usedInProject',
}

function shortIri(iri: string): string {
  return IRI_LABELS[iri] ?? iri.split(/[/#]/).pop() ?? iri
}

type MetaRole = keyof MetaProfilePatch

const META_ROLE_COLS: MetaRole[] = [
  'title_props', 'shortname_props', 'description_props', 'creator_props',
  'contributor_props', 'publisher_props', 'license_props', 'homepage_props',
  'version_info_props', 'version_iri_props', 'prefix_props', 'namespace_uri_props',
  'created_props', 'modified_props', 'language_props', 'citation_props', 'funding_props',
  'status_props', 'syntax_props',
  'see_also_props', 'is_defined_by_props',
  'competency_question_props', 'endorsed_by_props', 'relies_on_props',
  'similar_props', 'generalizes_props', 'specializes_props',
  'known_usage_props', 'used_in_project_props',
]

const ROLE_LABEL: Record<MetaRole, string> = {
  title_props: 'Title',
  shortname_props: 'Shortname',
  description_props: 'Description',
  creator_props: 'Creator',
  contributor_props: 'Contributor',
  publisher_props: 'Publisher',
  license_props: 'License',
  homepage_props: 'Homepage',
  version_info_props: 'Version Info',
  version_iri_props: 'Version IRI',
  prefix_props: 'NS Prefix',
  namespace_uri_props: 'NS URI',
  created_props: 'Created',
  modified_props: 'Modified',
  language_props: 'Language',
  citation_props: 'Citation',
  funding_props: 'Funding',
  status_props: 'Status',
  syntax_props: 'Syntax',
  see_also_props: 'See Also',
  is_defined_by_props: 'Is Defined By',
  competency_question_props: 'Competency Question',
  endorsed_by_props: 'Endorsed By',
  relies_on_props: 'Relies On',
  similar_props: 'Similar',
  generalizes_props: 'Generalizes',
  specializes_props: 'Specializes',
  known_usage_props: 'Known Usage',
  used_in_project_props: 'Used In Project',
}

interface MetaProp {
  iri: string
  label: string
  propLabel: string | null
  values: string[]
  role: MetaRole | null
}

function valuePreview(values: string[]): string {
  if (values.length === 0) return '—'
  const v = String(values[0])
  return v.length > 40 ? v.slice(0, 38) + '…' : v
}

function buildMetaProps(
  profile: OntologyMetaProfile,
  candidatesData: Record<string, unknown>,
): MetaProp[] {
  const roleMap = new Map<string, MetaRole>()
  for (const col of META_ROLE_COLS) {
    for (const iri of ((profile as any)[col] as string[] | undefined) ?? []) {
      roleMap.set(iri, col)
    }
  }

  const seen = new Set<string>()
  const all: MetaProp[] = []

  // Candidates keyed by role name (e.g. "title") and "unknown"
  for (const [roleKey, items] of Object.entries(candidatesData)) {
    if (roleKey === 'version_id' || !Array.isArray(items)) continue
    for (const item of items as { iri: string; values: Array<{ value: string } | string>; label?: string | null }[]) {
      if (!seen.has(item.iri)) {
        seen.add(item.iri)
        const valueStrings = (item.values ?? []).map(v => typeof v === 'string' ? v : v.value)
        all.push({
          iri: item.iri,
          label: shortIri(item.iri),
          propLabel: item.label ?? null,
          values: valueStrings,
          role: roleMap.get(item.iri) ?? null,
        })
      }
    }
  }

  // Include any assigned props not in detection candidates
  for (const [iri, role] of roleMap.entries()) {
    if (!seen.has(iri)) {
      all.push({ iri, label: shortIri(iri), propLabel: null, values: [], role })
    }
  }

  return all
}

export default function MetaProfileEditor({
  ontologyId,
  versionId,
}: {
  ontologyId: string
  versionId: string
}) {
  const { data: profile, isLoading: profileLoading } = useOntologyMeta(ontologyId, versionId)
  const { data: candidates } = useMetaCandidates(ontologyId, versionId)
  const patch = usePatchMeta(ontologyId, versionId)
  const detect = useDetectMeta(ontologyId, versionId)
  const [roleEdits, setRoleEdits] = useState<Record<string, MetaRole | null>>({})

  if (profileLoading) {
    return <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 12 }}>Loading…</div>
  }

  if (!profile) {
    return (
      <div style={{ padding: '1rem' }}>
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginBottom: 12 }}>No metadata profile detected yet.</div>
        <button
          onClick={() => detect.mutate()}
          disabled={detect.isPending}
          style={{ padding: '6px 14px', borderRadius: 4, border: 'none', background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 12, cursor: 'pointer' }}
        >
          {detect.isPending ? 'Running…' : 'Detect Metadata'}
        </button>
        {detect.isError && (
          <div style={{ marginTop: 8, color: 'var(--red)', fontSize: 11 }}>
            Detection failed: {(detect.error as Error)?.message ?? 'unknown error'}
          </div>
        )}
      </div>
    )
  }

  const candidatesData = (candidates ?? {}) as Record<string, unknown>
  const props = buildMetaProps(profile, candidatesData)
  const isDirty = Object.keys(roleEdits).length > 0

  function effectiveRole(p: MetaProp): MetaRole | null {
    return p.iri in roleEdits ? roleEdits[p.iri] : p.role
  }

  function handleSave() {
    const groups = META_ROLE_COLS.reduce((acc, col) => {
      acc[col] = []
      return acc
    }, {} as Record<MetaRole, string[]>)
    for (const p of props) {
      const r = effectiveRole(p)
      if (r) groups[r].push(p.iri)
    }
    patch.mutate(groups, { onSuccess: () => setRoleEdits({}) })
  }

  return (
    <div style={{ padding: '12px 16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <span style={{
          fontSize: 10, padding: '1px 8px', borderRadius: 10,
          background: profile.status === 'user_confirmed' ? 'rgba(63,185,80,0.1)' : 'rgba(88,166,255,0.1)',
          color: profile.status === 'user_confirmed' ? 'var(--green)' : 'var(--blue)',
          border: `1px solid ${profile.status === 'user_confirmed' ? 'rgba(63,185,80,0.25)' : 'rgba(88,166,255,0.25)'}`,
        }}>
          {profile.status === 'user_confirmed' ? '● confirmed' : '⟳ auto-detected'}
        </span>
        <button
          onClick={() => detect.mutate()}
          disabled={detect.isPending}
          style={{ fontSize: 10, color: 'var(--text-dim)', background: 'none', border: 'none', cursor: 'pointer' }}
        >
          {detect.isPending ? 'Re-detecting…' : 'Re-detect'}
        </button>
        {detect.isError && (
          <span style={{ fontSize: 10, color: 'var(--red)' }}>
            {(detect.error as Error)?.message ?? 'error'}
          </span>
        )}
      </div>

      {props.length === 0 ? (
        <div>
          <div style={{ color: 'var(--text-dim)', fontSize: 12, marginBottom: 10 }}>
            No ontology-level properties found in the ontology header.
          </div>
          <button
            onClick={() => detect.mutate()}
            disabled={detect.isPending}
            style={{ padding: '6px 14px', borderRadius: 4, border: 'none', background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 12, cursor: 'pointer' }}
          >
            {detect.isPending ? 'Scanning…' : 'Scan Now'}
          </button>
        </div>
      ) : (
        <>
          <div style={{
            display: 'grid', gridTemplateColumns: '1fr 1fr 120px', gap: 8,
            paddingBottom: 6, marginBottom: 2, borderBottom: '1px solid var(--border)',
          }}>
            <span style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 0.6 }}>Property</span>
            <span style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 0.6 }}>Value</span>
            <span style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 0.6 }}>Role</span>
          </div>
          {props.map(p => (
            <div key={p.iri} style={{
              display: 'grid', gridTemplateColumns: '1fr 1fr 120px', gap: 8,
              padding: '4px 0', alignItems: 'center',
              borderBottom: '1px solid color-mix(in srgb, var(--border) 40%, transparent)',
            }}>
              <div title={p.iri} style={{ overflow: 'hidden' }}>
                <div style={{ fontSize: 11, color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {p.propLabel ?? p.label}
                </div>
                {p.propLabel && (
                  <div style={{ fontSize: 9, color: 'var(--text-dim)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {p.label}
                  </div>
                )}
              </div>
              <span title={p.values.join('; ')} style={{ fontSize: 11, color: 'var(--text-dim)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {valuePreview(p.values)}
              </span>
              <select
                value={effectiveRole(p) ?? ''}
                onChange={e => setRoleEdits(prev => ({
                  ...prev,
                  [p.iri]: (e.target.value || null) as MetaRole | null,
                }))}
                style={{
                  fontSize: 11, padding: '2px 4px', borderRadius: 4,
                  border: '1px solid var(--border)', background: 'var(--bg)',
                  color: 'var(--text)', cursor: 'pointer', width: '100%',
                }}
              >
                <option value="">—</option>
                {META_ROLE_COLS.map(col => (
                  <option key={col} value={col}>{ROLE_LABEL[col]}</option>
                ))}
              </select>
            </div>
          ))}
        </>
      )}

      <div style={{ marginTop: 16, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
        <button
          onClick={handleSave}
          disabled={!isDirty || patch.isPending}
          style={{
            padding: '6px 16px', borderRadius: 4, border: 'none',
            background: isDirty ? 'var(--accent)' : 'var(--bg-secondary)',
            color: isDirty ? 'var(--on-accent)' : 'var(--text-dim)',
            fontSize: 12, cursor: isDirty ? 'pointer' : 'default',
          }}
        >
          {patch.isPending ? 'Saving…' : 'Save and re-index'}
        </button>
        {patch.isSuccess && <span style={{ marginLeft: 10, color: 'var(--green)', fontSize: 11 }}>✓ Saved</span>}
        {patch.isError && <span style={{ marginLeft: 10, color: 'var(--red)', fontSize: 11 }}>{(patch.error as Error)?.message ?? 'Save failed'}</span>}
      </div>
    </div>
  )
}
