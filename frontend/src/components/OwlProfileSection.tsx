import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, ManchesterToken, OwlProfileRecord, ProfileResult } from '../lib/api'

// ---------------------------------------------------------------------------
// Inline Manchester renderer (lighter-weight than the full ManchesterFrame)
// ---------------------------------------------------------------------------

function ManchesterInline({ tokens }: { tokens: ManchesterToken[] }) {
  return (
    <code style={{ fontSize: 10, wordBreak: 'break-all', fontFamily: 'monospace' }}>
      {tokens.map((t, i) => {
        if (t.t === 'text') {
          return <span key={i}>{t.v}</span>
        }
        if (t.t === 'iri') {
          return (
            <span
              key={i}
              style={{ color: 'var(--accent, #7eb3f5)', fontWeight: 500 }}
            >
              {t.label ?? t.iri}
            </span>
          )
        }
        return null
      })}
    </code>
  )
}

const PROFILE_LABELS: Record<string, string> = {
  el: 'OWL 2 EL',
  rl: 'OWL 2 RL',
  ql: 'OWL 2 QL',
  dl: 'OWL 2 DL',
}

function ProfileCard({
  name,
  result,
}: {
  name: string
  result: ProfileResult
}) {
  const [expanded, setExpanded] = useState(false)
  const label = PROFILE_LABELS[name] ?? name.toUpperCase()
  const inProfile = result.in_profile
  const hasViolations = !inProfile && result.total_violations > 0

  const sortedViolations = Object.entries(result.violations_by_axiom_type).sort(
    (a, b) => b[1] - a[1]
  )

  return (
    <div
      data-testid={`profile-card-${name}`}
      style={{
        background: 'var(--bg-secondary)',
        border: `1px solid ${inProfile ? 'rgba(63,185,80,0.3)' : 'rgba(224,108,117,0.3)'}`,
        borderRadius: 'var(--radius)',
        padding: '0.75rem',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        {inProfile ? (
          <span
            data-testid="profile-check"
            style={{ color: '#3fb950', fontSize: 16, fontWeight: 700 }}
          >
            ✓
          </span>
        ) : (
          <span
            data-testid="profile-x"
            style={{ color: '#e06c75', fontSize: 16, fontWeight: 700 }}
          >
            ✗
          </span>
        )}
        <span
          style={{
            fontSize: 'var(--font-size-sm)',
            fontWeight: 600,
            color: 'var(--text)',
          }}
        >
          {label}
        </span>
      </div>

      {inProfile ? (
        <p
          style={{
            fontSize: 11,
            color: '#3fb950',
            margin: 0,
          }}
        >
          Conformant
        </p>
      ) : (
        <p
          style={{
            fontSize: 11,
            color: '#e06c75',
            margin: 0,
          }}
        >
          {result.total_violations.toLocaleString()} violation
          {result.total_violations !== 1 ? 's' : ''}
        </p>
      )}

      {hasViolations && (
        <div style={{ marginTop: 8 }}>
          <button
            data-testid={`expander-${name}`}
            onClick={() => setExpanded(v => !v)}
            style={{
              fontSize: 10,
              padding: '2px 7px',
              borderRadius: 3,
              border: '1px solid var(--border)',
              background: 'none',
              color: 'var(--text-dim)',
              cursor: 'pointer',
              textTransform: 'uppercase',
              letterSpacing: 0.5,
            }}
            onMouseEnter={e => {
              e.currentTarget.style.borderColor = 'var(--text-muted)'
            }}
            onMouseLeave={e => {
              e.currentTarget.style.borderColor = 'var(--border)'
            }}
          >
            {expanded ? 'Collapse' : 'Details'}
          </button>

          {expanded && (
            <div data-testid={`violations-${name}`} style={{ marginTop: 8 }}>
              <div
                style={{
                  fontSize: 10,
                  textTransform: 'uppercase',
                  letterSpacing: 1,
                  color: 'var(--text-dim)',
                  marginBottom: 4,
                }}
              >
                By axiom type
              </div>
              <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {sortedViolations.map(([type, count]) => (
                  <li
                    key={type}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      fontSize: 11,
                      padding: '2px 0',
                      color: 'var(--text-muted)',
                      borderBottom: '1px solid rgba(255,255,255,0.04)',
                    }}
                  >
                    <code style={{ color: 'var(--text)' }}>{type}</code>
                    <span>{count.toLocaleString()}</span>
                  </li>
                ))}
              </ul>

              {result.sample_violations.length > 0 && (
                <div style={{ marginTop: 8 }}>
                  <div
                    style={{
                      fontSize: 10,
                      textTransform: 'uppercase',
                      letterSpacing: 1,
                      color: 'var(--text-dim)',
                      marginBottom: 4,
                    }}
                  >
                    Sample violations
                  </div>
                  <table
                    style={{
                      width: '100%',
                      borderCollapse: 'collapse',
                      fontSize: 11,
                    }}
                  >
                    <thead>
                      <tr>
                        <th
                          style={{
                            textAlign: 'left',
                            padding: '2px 4px',
                            color: 'var(--text-dim)',
                            fontWeight: 500,
                          }}
                        >
                          Axiom type
                        </th>
                        <th
                          style={{
                            textAlign: 'left',
                            padding: '2px 4px',
                            color: 'var(--text-dim)',
                            fontWeight: 500,
                          }}
                        >
                          Subject / Details
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.sample_violations.slice(0, 10).map((v, i) => (
                        <tr
                          key={i}
                          style={{
                            borderTop: '1px solid rgba(255,255,255,0.04)',
                          }}
                        >
                          <td
                            style={{
                              padding: '2px 4px',
                              color: 'var(--text)',
                              whiteSpace: 'nowrap',
                            }}
                          >
                            <code>{v.axiom_type}</code>
                          </td>
                          <td
                            style={{
                              padding: '2px 4px',
                              color: 'var(--text-muted)',
                              wordBreak: 'break-all',
                              fontSize: 10,
                            }}
                          >
                            {v.manchester && v.manchester.length > 0 ? (
                              <ManchesterInline tokens={v.manchester} />
                            ) : v.details ? (
                              v.details
                            ) : v.subject_iri ? (
                              v.subject_iri.length > 80
                                ? `…${v.subject_iri.slice(-70)}`
                                : v.subject_iri
                            ) : (
                              '—'
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function OwlProfileSection({
  ontologyId,
  versionId,
}: {
  ontologyId: string
  versionId: string
}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['owl-profile', ontologyId, versionId],
    queryFn: () => api.owl_profile.version(ontologyId, versionId),
    retry: false,
  })

  if (isLoading) {
    return (
      <div
        style={{
          padding: '1rem',
          color: 'var(--text-dim)',
          fontSize: 'var(--font-size-sm)',
        }}
      >
        Loading…
      </div>
    )
  }

  const status = (error as { status?: number } | null)?.status

  if (error) {
    if (status === 404) {
      return (
        <section id="owl-profile" style={{ padding: '1rem' }}>
          <h2
            style={{
              fontSize: '0.95rem',
              fontWeight: 600,
              marginBottom: '0.5rem',
            }}
          >
            OWL 2 Profile
          </h2>
          <p
            style={{
              color: 'var(--text-dim)',
              fontSize: 'var(--font-size-sm)',
            }}
          >
            OWL profile not yet computed — will be available after the next
            reindex.
          </p>
        </section>
      )
    }
    return (
      <section id="owl-profile" style={{ padding: '1rem' }}>
        <h2
          style={{ fontSize: '0.95rem', fontWeight: 600, marginBottom: '0.5rem' }}
        >
          OWL 2 Profile
        </h2>
        <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
          Failed to load OWL profile.
        </p>
      </section>
    )
  }

  if (!data) return null

  const record = data as OwlProfileRecord
  const profiles: Array<keyof typeof PROFILE_LABELS> = ['el', 'rl', 'ql', 'dl']

  return (
    <section id="owl-profile" style={{ padding: '1rem' }}>
      <h2
        style={{
          fontSize: '0.95rem',
          fontWeight: 600,
          marginBottom: '0.75rem',
        }}
      >
        OWL 2 Profile
      </h2>

      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '0.5rem',
          marginBottom: '1rem',
        }}
      >
        {profiles.map(p => (
          <ProfileCard key={p} name={p} result={record[p]} />
        ))}
      </div>

      <p
        data-testid="last-computed"
        style={{ marginTop: '0.75rem', color: 'var(--text-muted)', fontSize: 11 }}
      >
        Last computed: {new Date(record.indexed_at).toLocaleString()}
      </p>
    </section>
  )
}
