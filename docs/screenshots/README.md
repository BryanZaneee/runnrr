# README screenshots

Capture the local workstation with the runtime running at http://127.0.0.1:8001.

```sh
npm ci
npx playwright install chromium
npm run capture
```

Requires Node.js and `cwebp`. The script uses a 1440 × 960 viewport and writes
`workstation-local.webp`. It does not submit a paid model request. Review the
image for private content and error states before publishing it.
