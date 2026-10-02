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
 *  children, recursing to real depth (visual indent clamped, not the row
 *  itself). Rows with no match among the seeded asks (an orphaned
 *  parent_id), and any node whose ancestry loops back on itself (including
 *  a self-parent), are promoted to a root instead of being discarded —
 *  every ask renders exactly once, no exceptions. */
function nestAsks(asks) {
  const byId = new Map(asks.map(a => [a.id, a]))

  // A node is cyclic if walking parent_id from it ever revisits a node
  // already seen in THIS walk. That makes it a root regardless of whether
  // its parent_id otherwise resolves to a real ask.
  function isCyclic(id) {
    const seen = new Set()
    let cur = id
    while (true) {
      if (seen.has(cur)) return true
      seen.add(cur)
      const ask = byId.get(cur)
      if (!ask || !ask.parent_id || !byId.has(ask.parent_id)) return false
      cur = ask.parent_id
    }
  }

  const roots = asks.filter(a => !a.parent_id || !byId.has(a.parent_id) || isCyclic(a.id))

  const childrenOf = new Map()
  for (const ask of asks) {
    if (ask.parent_id && byId.has(ask.parent_id) && !isCyclic(ask.id)) {
      const siblings = childrenOf.get(ask.parent_id) ?? []
      siblings.push(ask)
      childrenOf.set(ask.parent_id, siblings)
    }
  }

  const rows = []
  const visited = new Set()
  function walk(ask, depth) {
    if (visited.has(ask.id)) return // defence in depth against malformed data
    visited.add(ask.id)
    rows.push({ ask, depth: Math.min(depth, 3) })
    for (const child of childrenOf.get(ask.id) ?? []) {
      walk(child, depth + 1)
    }
  }
  for (const root of roots) {
    walk(root, 0)
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
