import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import ts from 'typescript'

// Exercise the actual browser sampler with a deterministic video/clock, using
// the project's existing TypeScript compiler and Node's built-in test runner.
const source = await readFile(new URL('../src/media.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } })
const { CameraSampler } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)

function camera(t) {
  let now = 0, callback, count = 0
  t.mock.method(performance, 'now', () => now)
  const oldDocument = globalThis.document
  globalThis.document = {
    createElement() {
      count++
      let frame
      return { width: 0, height: 0, getContext: () => ({ drawImage: (video) => { frame = video.frame } }), toDataURL: () => frame }
    },
  }
  t.after(() => { if (oldDocument === undefined) delete globalThis.document; else globalThis.document = oldDocument })
  const video = {
    readyState: 2, videoWidth: 640, videoHeight: 480, frame: 'open',
    requestVideoFrameCallback(next) { callback = next; return 1 },
    cancelVideoFrameCallback() { callback = null },
  }
  const controller = new AbortController()
  const sampler = new CameraSampler(video, 0, controller.signal)
  t.after(() => sampler.stop())
  return {
    sampler, controller, canvases: () => count,
    frame(time, state = 'open', mediaTime = time / 1000) {
      now = time; video.frame = state
      const next = callback; callback = null
      next?.(time, { mediaTime })
    },
  }
}

test('a short blink is retained while a previous HTTP request is in flight', async (t) => {
  const c = camera(t)
  c.frame(50)
  await c.sampler.take() // sent to the server; its reply takes until 250 ms
  c.frame(100, 'closed')
  c.frame(150, 'open')
  c.frame(200, 'open')
  assert.deepEqual((await c.sampler.take()).map(({ image, offset_ms }) => [image, offset_ms]),
    [['closed', 100], ['open', 150], ['open', 200]])
  assert.equal(c.canvases(), 1)
})

test('new prompts discard previously captured evidence, and duplicate video frames are ignored', async (t) => {
  const c = camera(t)
  c.frame(50, 'closed')
  c.sampler.discard()
  c.frame(100, 'closed', .05) // same physical frame as before the prompt
  c.frame(150, 'open')
  assert.deepEqual((await c.sampler.take()).map((frame) => frame.image), ['open'])
})

test('a slow consumer has a bounded queue containing the freshest frames', async (t) => {
  const c = camera(t)
  for (let time = 50; time <= 600; time += 50) c.frame(time)
  const batch = await c.sampler.take()
  assert.equal(batch.length, 6)
  assert.equal(batch[0].offset_ms, 350)
  assert.equal(batch.at(-1).offset_ms, 600)
})

test('canceling a scan stops sampling and releases a pending consumer', async (t) => {
  const c = camera(t)
  const pending = c.sampler.take()
  c.controller.abort()
  await assert.rejects(pending, { name: 'AbortError' })
  c.frame(50)
  assert.equal(c.canvases(), 0)
})
