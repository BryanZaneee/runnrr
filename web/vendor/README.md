# Vendored UI assets

Pinned upstream distributions, served locally so rendering does not depend on a CDN:

- [Marked 18.0.14](https://github.com/markedjs/marked/releases/tag/v18.0.14): `marked.mjs`, from the published npm package's `lib/marked.esm.js`. MIT; see `MARKED-LICENSE`.
- [DOMPurify 3.4.15](https://github.com/cure53/DOMPurify/releases/tag/3.4.15): `purify.mjs`, upstream `dist/purify.es.mjs`. Apache-2.0 OR MPL-2.0; see `DOMPURIFY-LICENSE`.
- [Heroicons 2.2.0](https://github.com/tailwindlabs/heroicons/tree/v2.2.0/optimized/24/outline): selected outline SVGs in `icons/`, unchanged from upstream. MIT; see `icons/LICENSE`.

Update the pinned files and this list together. Verify Markdown sanitization and UI screenshots after updates. The workstation uses system fonts with no external font requests.

The layout reference copyright and permission notice is retained in
`LAYOUT-LICENSE`.

- Lucide 0.468.0: `panel-left.svg` and `panel-right.svg` from the tagged upstream icons directory. ISC; see `LUCIDE-LICENSE`. Other new icons use the pinned Heroicons release above.
