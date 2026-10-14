import { useEffect, useState } from 'react'

/**
 * Copies a permalink to the clipboard with transient "Copied!" feedback.
 * Used by both compare surfaces (cross-ontology Compare page and the per-ontology
 * History tab) so a specific paired comparison can be shared by URL.
 *
 * `getUrl` is called at click time so the latest selection is captured. Falls
 * back to a legacy execCommand copy when the async Clipboard API is unavailable
 * (non-secure contexts / older browsers).
 */
export default function CopyLinkButton({
  getUrl,
  title = 'Copy a shareable link to this comparison',
  compact = false,
}: {
  getUrl: () => string
  title?: string
  compact?: boolean
}) {
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return
    const id = setTimeout(() => setCopied(false), 1800)
    return () => clearTimeout(id)
  }, [copied])

  async function copy() {
    const url = getUrl()
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(url)
      } else {
        const ta = document.createElement('textarea')
        ta.value = url
        ta.style.position = 'fixed'
        ta.style.opacity = '0'
        document.body.appendChild(ta)
        ta.select()
        document.execCommand('copy')
        document.body.removeChild(ta)
      }
      setCopied(true)
    } catch {
      // Clipboard blocked — surface the URL so the user can copy manually.
      window.prompt('Copy this link:', url)
    }
  }

  return (
    <button
      type="button"
      onClick={copy}
      title={title}
      aria-label={title}
      style={{
        background: 'var(--bg-secondary)', border: '1px solid var(--border)',
        borderRadius: 4, padding: compact ? '3px 8px' : '6px 12px',
        color: copied ? 'var(--accent)' : 'var(--text-dim)',
        fontSize: compact ? 11 : 12, cursor: 'pointer',
        display: 'inline-flex', alignItems: 'center', gap: 5, fontFamily: 'inherit',
        whiteSpace: 'nowrap',
      }}
    >
      <span aria-hidden="true">{copied ? '✓' : '🔗'}</span>
      {copied ? 'Link copied' : 'Copy link'}
    </button>
  )
}
