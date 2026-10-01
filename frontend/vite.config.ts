import fs from 'node:fs'
import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

/**
 * Plain http by default. A browser treats http://localhost as a secure context, so the camera
 * and microphone work there without any certificate and without a "not secure" warning.
 *
 * HTTPS is for reaching the dev server from a phone on the same network: a plain-http LAN
 * address is not a secure context and getUserMedia is refused before any permission prompt
 * appears. Start with `DEV_HTTPS=1 npm run dev` once `scripts/dev-cert.sh` has issued the
 * self-signed certificate into frontend/certs/, and accept the browser's warning once.
 */
// `import.meta.dirname`, not `__dirname`: vite's native config loader does not provide the
// CommonJS globals and warns that relying on them will stop working.
const certDir = path.resolve(import.meta.dirname, 'certs')
const key = path.join(certDir, 'dev-key.pem')
const cert = path.join(certDir, 'dev-cert.pem')
const wantHttps = process.env.DEV_HTTPS === '1'
const https =
  wantHttps && fs.existsSync(key) && fs.existsSync(cert)
    ? { key: fs.readFileSync(key), cert: fs.readFileSync(cert) }
    : undefined

if (wantHttps && !https) {
  console.warn(
    '[painsense] DEV_HTTPS=1 but frontend/certs holds no certificate; serving over http.\n' +
      '            Run ./scripts/dev-cert.sh to issue one.',
  )
}

// The API is reached through the dev server rather than directly, so the page and the API
// share an origin and the refresh cookie survives a reload. API_PROXY picks the backend when
// it is not on 8000.
const api = process.env.API_PROXY ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Bound to every interface so a phone on the same network can reach it. Development only.
    host: true,
    port: 5173,
    https,
    proxy: {
      '/api': { target: api, changeOrigin: true },
    },
  },
})
