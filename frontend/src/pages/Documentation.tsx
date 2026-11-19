import MarkdownPage from '../components/MarkdownPage'
import docsMd from '../content/documentation.md?raw'

export default function Documentation() {
  return <MarkdownPage source={docsMd} />
}
