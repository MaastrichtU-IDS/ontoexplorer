import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeSlug from 'rehype-slug'
import './MarkdownPage.css'

// Cross-page links in the source markdown (e.g. `documentation.md#submitting-an-ontology`)
// map to app routes so they navigate within the SPA instead of 404ing.
const FILE_ROUTES: Record<string, string> = {
  'about.md': '/about',
  'documentation.md': '/docs',
  'privacy.md': '/privacy',
  'contact.md': '/contact',
}

/**
 * Renders a markdown document as a themed, in-app page. Headings get slug ids
 * (rehype-slug) so the in-document table of contents and cross-page `#anchor`
 * links resolve; `{{key}}` tokens in the source are replaced from `substitutions`.
 */
export default function MarkdownPage({
  source,
  substitutions,
}: {
  source: string
  substitutions?: Record<string, string>
}) {
  const location = useLocation()
  const navigate = useNavigate()

  let text = source
  if (substitutions) {
    for (const [k, v] of Object.entries(substitutions)) {
      text = text.split(`{{${k}}}`).join(v)
    }
  }

  // After the content renders, honour a #hash (direct load or cross-page jump);
  // otherwise start at the top.
  useEffect(() => {
    if (location.hash) {
      const el = document.getElementById(decodeURIComponent(location.hash.slice(1)))
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' })
        return
      }
    }
    window.scrollTo(0, 0)
  }, [location.pathname, location.hash, text])

  const components: Components = {
    a({ href, children }) {
      const h = href ?? ''
      const cross = h.match(/^([\w-]+\.md)(#.+)?$/)
      if (cross && FILE_ROUTES[cross[1]]) {
        const to = FILE_ROUTES[cross[1]] + (cross[2] ?? '')
        return <a href={to} onClick={(e) => { e.preventDefault(); navigate(to) }}>{children}</a>
      }
      if (h.startsWith('#')) {
        return (
          <a
            href={h}
            onClick={(e) => {
              e.preventDefault()
              const el = document.getElementById(decodeURIComponent(h.slice(1)))
              if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
              if (location.hash !== h) navigate(location.pathname + h)
            }}
          >
            {children}
          </a>
        )
      }
      if (/^https?:/i.test(h)) {
        return <a href={h} target="_blank" rel="noopener noreferrer">{children}</a>
      }
      return <a href={h}>{children}</a>
    },
    table({ children }) {
      return <div className="md-tablewrap"><table>{children}</table></div>
    },
  }

  return (
    <div className="markdown-page">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSlug]} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  )
}
