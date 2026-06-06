// Launch Open Notebook inside a native Glimpse WebView window.
//
// Glimpse renders inline HTML; we hand it a tiny shim that navigates the
// WebView to the locally running Open Notebook frontend. Keep this Node
// process alive while the window is open.
//
// Usage: node scripts/glimpse-launch.mjs [url]
import { execSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { dirname } from 'node:path'
import { pathToFileURL } from 'node:url'

const require = createRequire(import.meta.url)

// glimpseui is typically installed globally. Resolve it from (in order):
// a local install, GLIMPSE_PKG_DIR, then the npm global root.
// require.resolve's `paths` wants the directory CONTAINING node_modules, so we
// use the parent of `npm root -g` (which returns the node_modules dir itself).
function resolveGlimpse() {
  const candidates = [process.env.GLIMPSE_PKG_DIR].filter(Boolean)
  try {
    candidates.push(dirname(execSync('npm root -g', { encoding: 'utf8' }).trim()))
  } catch {
    /* npm not on PATH — fall through */
  }
  try {
    return require.resolve('glimpseui') // local dep, if present
  } catch {
    /* not local */
  }
  for (const dir of candidates) {
    try {
      return require.resolve('glimpseui', { paths: [dir] })
    } catch {
      /* try next */
    }
  }
  throw new Error(
    "Could not find 'glimpseui'. Install it with: npm install -g glimpseui"
  )
}

// On Windows, dynamic import() requires a file:// URL, not a drive path.
const { open } = await import(pathToFileURL(resolveGlimpse()).href)

const url = process.argv[2] || 'http://localhost:3000/notebooklm'

const html = `<!doctype html><html><head><meta charset="utf-8">
<title>Open Notebook</title>
<style>
  html,body{margin:0;height:100%;background:#0b0b0c;color:#e5e7eb;
    font:14px/1.5 system-ui,Segoe UI,sans-serif;display:flex;
    align-items:center;justify-content:center}
</style></head>
<body>
  <div>Loading Open Notebook…</div>
  <script>location.replace(${JSON.stringify(url)})</script>
</body></html>`

const win = open(html, {
  width: 1280,
  height: 860,
  title: 'Open Notebook',
})

win.on('close', () => process.exit(0))
console.log('Glimpse window opened ->', url)
