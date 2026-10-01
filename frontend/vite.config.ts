import fs from 'node:fs'
import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

/**
 * HTTPS is read from frontend/certs/ when it is there, because camera and microphone access
 * needs a secure context. A browser treats localhost as secure and a plain-http LAN address as
 * not, so reaching the dev server from a phone at http://192.168.x.x:5173 means getUserMedia is
 * refused before any permission prompt appears. `scripts/dev-cert.sh` issues the certificate.
 *
 * Without the certificate the server still starts, over http, and everything but camera and
 * microphone works — on localhost those work too.
 */
// `import.meta.dirname`, not `__dirname`: vite's native config loader does not provide the
// CommonJS globals and warns that relying on them will stop working.
const certDir = path.resolve(import.meta.dirname, 'certs')
const key = path.join(certDir, 'dev-key.pem')
const cert = path.join(certDir, 'dev-cert.pem')
const https =
  fs.existsSync(key) && fs.existsSync(cert)
    ? { key: fs.readFileSync(key), cert: fs.readFileSync(cert) }
    : undefined

if (!https) {
  console.warn(
    '[painsense] no dev certificate in frontend/certs — serving over http.\n' +
      '            Camera and microphone will work on localhost but not from a phone.\n' +
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
