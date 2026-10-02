// Tests for desktop/plugin.js's pure nestAsks() helper.
//
// plugin.js is a no-build runtime file (only '@hermes/plugin-sdk', 'react',
// 'react/jsx-runtime' are importable specifiers there, so this file cannot
// just `import` it directly without those modules present). nestAsks is a
// pure, dependency-free function, so it is extracted by source text and
// evaluated in isolation — same technique as plugin-sdk cookbook examples
// that keep pure helpers testable outside the bundle.
//
// Run: node tests/nest_asks.test.mjs

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
const source = readFileSync(path.join(here, '..', 'desktop', 'plugin.js'), 'utf8')

const match = source.match(/function nestAsks\(asks\) \{[\s\S]*?\n\}/)
if (!match) {
  throw new Error('nestAsks function not found in desktop/plugin.js')
}

// eslint-disable-next-line no-new-func
const nestAsks = new Function(`${match[0]}\nreturn nestAsks;`)()

function run(name, fn) {
  try {
    fn()
    console.log(`ok - ${name}`)
  } catch (err) {
    console.error(`FAIL - ${name}`)
    console.error(err)
    process.exitCode = 1
  }
}

run('zero asks returns zero rows', () => {
  assert.deepEqual(nestAsks([]), [])
})

run('flat asks with no parent_id all render at depth 0', () => {
  const asks = [
    { id: 'a', parent_id: null },
    { id: 'b', parent_id: null }
  ]
  const rows = nestAsks(asks)
  assert.equal(rows.length, 2)
  assert.ok(rows.every(r => r.depth === 0))
})

run('a child nests under its parent at depth 1, parent first', () => {
  const asks = [
    { id: 'parent-1', parent_id: null },
    { id: 'child-1', parent_id: 'parent-1' }
  ]
  const rows = nestAsks(asks)
  assert.equal(rows.length, 2)
  assert.equal(rows[0].ask.id, 'parent-1')
  assert.equal(rows[0].depth, 0)
  assert.equal(rows[1].ask.id, 'child-1')
  assert.equal(rows[1].depth, 1)
})

run('an orphaned parent_id (parent not in the set) renders at depth 0, not dropped', () => {
  const asks = [{ id: 'child-1', parent_id: 'missing-parent' }]
  const rows = nestAsks(asks)
  assert.equal(rows.length, 1)
  assert.equal(rows[0].ask.id, 'child-1')
  assert.equal(rows[0].depth, 0)
})

run('a grandchild nests at depth 2, after its parent and grandparent', () => {
  const asks = [
    { id: 'a', parent_id: null },
    { id: 'b', parent_id: 'a' },
    { id: 'c', parent_id: 'b' }
  ]
  const rows = nestAsks(asks)
  assert.equal(rows.length, asks.length)
  assert.deepEqual(rows.map(r => r.ask.id), ['a', 'b', 'c'])
  assert.deepEqual(rows.map(r => r.depth), [0, 1, 2])
})

run('a great-grandchild nests at depth 3, nothing vanishes', () => {
  const asks = [
    { id: 'a', parent_id: null },
    { id: 'b', parent_id: 'a' },
    { id: 'c', parent_id: 'b' },
    { id: 'd', parent_id: 'c' }
  ]
  const rows = nestAsks(asks)
  assert.equal(rows.length, asks.length)
  assert.deepEqual(rows.map(r => r.ask.id), ['a', 'b', 'c', 'd'])
  assert.deepEqual(rows.map(r => r.depth), [0, 1, 2, 3])
})

run('a self-parent (s->s) is not lost: becomes a root', () => {
  const asks = [{ id: 's', parent_id: 's' }]
  const rows = nestAsks(asks)
  assert.equal(rows.length, asks.length)
  assert.equal(rows[0].ask.id, 's')
})

run('a two-node cycle (p->q->p) loses nothing', () => {
  const asks = [
    { id: 'p', parent_id: 'q' },
    { id: 'q', parent_id: 'p' }
  ]
  const rows = nestAsks(asks)
  assert.equal(rows.length, asks.length)
  assert.deepEqual(new Set(rows.map(r => r.ask.id)), new Set(['p', 'q']))
})

run('a three-node cycle (x->y->z->x) loses nothing', () => {
  const asks = [
    { id: 'x', parent_id: 'z' },
    { id: 'y', parent_id: 'x' },
    { id: 'z', parent_id: 'y' }
  ]
  const rows = nestAsks(asks)
  assert.equal(rows.length, asks.length)
  assert.deepEqual(new Set(rows.map(r => r.ask.id)), new Set(['x', 'y', 'z']))
})

run('rows.length === asks.length is an invariant across mixed fixtures', () => {
  const fixtures = [
    [],
    [{ id: 'a', parent_id: null }, { id: 'b', parent_id: null }],
    [{ id: 'child-1', parent_id: 'missing-parent' }],
    [{ id: 'a', parent_id: null }, { id: 'b', parent_id: 'a' }, { id: 'c', parent_id: 'b' }],
    [{ id: 's', parent_id: 's' }],
    [{ id: 'p', parent_id: 'q' }, { id: 'q', parent_id: 'p' }]
  ]
  for (const asks of fixtures) {
    assert.equal(nestAsks(asks).length, asks.length)
  }
})

if (process.exitCode) {
  process.exit(process.exitCode)
}
