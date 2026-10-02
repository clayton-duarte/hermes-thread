/**
 * Thread — session-scoped ask tracking strip above the composer.
 *
 * Runtime desktop plugin: plain ESM, loaded uncompiled, hot-reloads on save.
 * Renders into `composer.top` (COMPOSER_AREAS.top) — the free banner strip
 * directly above the composer input. See hermes-thread card3 for the seam
 * verification; nothing else currently contributes there.
 *
 * UI is jsx() calls — JSX syntax will not parse here.
 *
 * Collapses to nothing (returns null) when the active session has no asks —
 * an empty bar above every composer is worse than no feature.
 */

import { COMPOSER_AREAS, host, useQuery, useValue } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'thread'

// Row metrics, mirroring cockpit's compact row language: no background, no
// font, no margins of our own — only the host's own CSS vars are used for
// colour so this strip always matches the active theme.
const ROW = 'flex items-center gap-1.5 px-1.5 py-0.5 text-[0.75rem] leading-none'

/** One ask row. State decides weight/strike-through; `depth` indents a
 *  child under its parent. */
function AskRow({ ask, depth }) {
  const current = ask.state === 'current'
  const completed = ask.state === 'completed'

  return jsx('div', {
    className: ROW,
    style: { paddingLeft: `${0.375 + depth * 0.75}rem` },
    children: jsxs('span', {
      className: 'min-w-0 flex-1 truncate',
      style: {
        color: current ? 'var(--accent)' : completed ? 'var(--muted-foreground)' : 'var(--foreground)',
        fontWeight: current ? 600 : 400,
        textDecoration: completed ? 'line-through' : 'none'
      },
      children: [
        ask.title,
        ask.reopened_count > 0 ? ` (reopened ${ask.reopened_count}x)` : ''
      ]
    })
  })
}

/** Groups flat rows by `parent_id` and renders parents followed by their
 *  children, each child indented one level. Rows with no match among the
 *  seeded asks (an orphaned parent_id) are rendered at depth 0, same as a
 *  row with no parent — never dropped. */
function nestAsks(asks) {
  const byId = new Map(asks.map(a => [a.id, a]))
  const roots = asks.filter(a => !a.parent_id || !byId.has(a.parent_id))
  const childrenOf = new Map()

  for (const ask of asks) {
    if (ask.parent_id && byId.has(ask.parent_id)) {
      const siblings = childrenOf.get(ask.parent_id) ?? []
      siblings.push(ask)
      childrenOf.set(ask.parent_id, siblings)
    }
  }

  const rows = []
  for (const root of roots) {
    rows.push({ ask: root, depth: 0 })
    for (const child of childrenOf.get(root.id) ?? []) {
      rows.push({ ask: child, depth: 1 })
    }
  }
  return rows
}

function AsksBar({ ctx }) {
  const sessionId = useValue(host.state.focusedSessionId)

  const { data } = useQuery({
    queryKey: [ID, 'asks', sessionId],
    queryFn: () => ctx.rest(`/asks?session_id=${encodeURIComponent(sessionId)}`),
    enabled: Boolean(sessionId),
    refetchOnWindowFocus: true
  })

  const asks = data?.asks ?? []

  if (!sessionId || asks.length === 0) {
    return null
  }

  const rows = nestAsks(asks)

  return jsx('div', {
    className: 'flex flex-col border-b',
    style: { borderColor: 'var(--border)' },
    children: rows.map(({ ask, depth }) => jsx(AskRow, { ask, depth, key: ask.id }))
  })
}

export default {
  id: 'thread',
  name: 'Thread',
  register(ctx) {
    ctx.register({
      id: 'asks-bar',
      area: COMPOSER_AREAS.top,
      render: () => jsx(AsksBar, { ctx })
    })
  }
}
