// Run from web/: node scripts/screencast-synthetic.mjs
// Uses the existing Python/PyAV environment and installed Edge; no device or ADB.
import { build } from 'vite'
import { chromium } from '@playwright/test'
import { createServer } from 'node:http'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import assert from 'node:assert/strict'

const root = fileURLToPath(new URL('../../', import.meta.url))
const python = process.env.PYTHON || path.join(root, '.venv', 'Scripts', 'python.exe')
const fixtureCode = String.raw`
import base64, json
from fractions import Fraction
import av, numpy as np
from web_server.screencast import encode_session, encode_packet, annexb_nals
output = bytearray()
for width, height in [(160, 96), (96, 160)]:
    encoder = av.CodecContext.create('libx264', 'w')
    encoder.width, encoder.height = width, height
    encoder.pix_fmt = 'yuv420p'
    encoder.time_base = Fraction(1, 30)
    encoder.options = {'preset': 'ultrafast', 'tune': 'zerolatency', 'profile': 'baseline', 'x264-params': 'keyint=10:repeat-headers=1:bframes=0'}
    output += encode_session(width, height)
    for index in range(20):
        image = np.zeros((height, width, 3), dtype=np.uint8)
        image[:, :, 1] = 180
        image[:, index * 3 % width:(index * 3 % width) + 12, 2] = 255
        frame = av.VideoFrame.from_ndarray(image, format='rgb24')
        frame.pts = index
        for packet in encoder.encode(frame):
            data = bytes(packet)
            nals = annexb_nals(data)
            config = b''.join(b'\x00\x00\x00\x01' + nal for nal in nals if nal[0] & 31 in (7, 8))
            if config:
                output += encode_packet(config, config=True)
            output += encode_packet(data, 9000000000000000 + index * 33333, key_frame=packet.is_keyframe)
    for packet in encoder.encode(None):
        output += encode_packet(bytes(packet), 9000000000666667, key_frame=packet.is_keyframe)
print(json.dumps({'wire': base64.b64encode(output).decode()}))
`
const fixture = spawnSync(python, ['-c', fixtureCode], { cwd: root, encoding: 'utf8' })
if (fixture.status !== 0) throw new Error(fixture.stderr || 'Synthetic H264 generation failed')
const wire = Buffer.from(JSON.parse(fixture.stdout).wire, 'base64')
const result = await build({
  configFile: false, logLevel: 'error', define: { 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, lib: { entry: path.join(root, 'web/src/composables/useDeviceStream.js'), formats: ['es'] } },
})
const bundle = (Array.isArray(result) ? result[0] : result).output.find((entry) => entry.type === 'chunk').code
let requests = 0
let disconnected = 0
const html = `<!doctype html><canvas></canvas><script type="module">
import {useDeviceStream} from '/stream.js';
window.testStream = useDeviceStream();
testStream.canvas.value = document.querySelector('canvas');
testStream.start();
</script>`
const server = createServer((req, res) => {
  if (req.url === '/stream.js') {
    res.writeHead(200, { 'Content-Type': 'text/javascript' }); res.end(bundle); return
  }
  if (req.url.startsWith('/api/device/stream?')) {
    requests += 1
    if (!req.url.includes('codec=h264')) {
      res.writeHead(500); res.end('Unexpected JPEG fallback'); return
    }
    res.writeHead(200, { 'Content-Type': 'application/x-adb-h264; version=1', 'Cache-Control': 'no-store' })
    let offset = 0
    // Fragment even the headers and keep the stream open until stop() aborts it.
    const timer = setInterval(() => {
      if (offset < wire.length) {
        const end = Math.min(offset + 173, wire.length)
        res.write(wire.subarray(offset, end)); offset = end
      }
    }, 30)
    req.on('close', () => { disconnected += 1; clearInterval(timer) })
    return
  }
  if (req.url.startsWith('/api/device/stream/status')) {
    res.writeHead(200, { 'Content-Type': 'application/json' }); res.end('{"state":"streaming"}'); return
  }
  res.writeHead(200, { 'Content-Type': 'text/html' }); res.end(html)
})
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
let browser
try {
  browser = await chromium.launch({
    headless: true,
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
      : { channel: 'msedge' }),
  })
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto(`http://127.0.0.1:${server.address().port}`)
  try {
    await page.waitForFunction(() => window.testStream?.live.value && document.querySelector('canvas').width === 96, null, { timeout: 20000 })
  } catch (err) {
    console.error(await page.evaluate(() => ({ codec: window.testStream?.codec.value, error: window.testStream?.error.value, live: window.testStream?.live.value, width: document.querySelector('canvas').width })), { requests, errors })
    throw err
  }
  const state = await page.evaluate(() => {
    const target = document.querySelector('canvas')
    const pixel = [...target.getContext('2d').getImageData(0, 0, 1, 1).data]
    const state = { codec: testStream.codec.value, width: target.width, height: target.height, pixel }
    testStream.stop()
    return state
  })
  assert.equal(state.codec, 'h264')
  assert.equal(state.width, 96)
  assert.equal(state.height, 160)
  assert.ok(state.pixel[1] > 100, 'Synthetic green frame must reach the canvas')
  await page.waitForTimeout(100)
  assert.equal(requests, 1, 'No hidden fallback or retry')
  assert.equal(disconnected, 1, 'Stop must cancel the streaming fetch')
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ passed: true, browser: await browser.version(), ...state, requests, disconnected }))
} finally {
  await browser?.close()
  await new Promise((resolve) => server.close(resolve))
}
