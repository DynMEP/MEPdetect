# MEPdetect branding & logo

## One place to change the logo everywhere

Edit **`mepdetect-frontend/assets/branding.js`**:

| Setting | Purpose |
|--------|---------|
| `logoUrl` | Path or URL to your logo image (default `/assets/logo.svg`) |
| `logoAlt` | Accessibility alt text |
| `wordmark` | Text shown next to the logo (set `showWordmark: false` if the image already includes the name) |
| `logoHeight` / `logoHeightLg` | Size in pixels (header vs login sidebar) |
| `homeUrl` | Where the logo link goes (default `/`) |
| `faviconUrl` | Optional browser tab icon |

Replace the file **`mepdetect-frontend/assets/logo.svg`** with your own SVG or PNG (update `logoUrl` if you use another filename).

## How pages pick up the logo

1. Pages load `branding.js` and `js/apply-branding.js`.
2. Any element with **`data-mep-brand`** is replaced with the logo + wordmark link.

Examples:

```html
<div data-mep-brand></div>                    <!-- header / sidebar -->
<div data-mep-brand data-mep-brand-size="lg"></div>  <!-- login panel -->
<div data-mep-brand data-mep-brand-href="/admin.html"></div>
```

## Pages using shared branding

- `mepdetect-landing-page.html` (served as `/` / `index.html`)
- `login.html`
- `dashboard.html`
- `admin.html`
- `verify-email.html`
- `pricing.html`
- `checkout.html`

Every page listed above uses the shared system. If you add a page, give it a `data-mep-brand` slot and load `/assets/branding.js` so it stays in step.

## Theme / colors

Global look is in **`mepdetect-frontend/css/mepdetect.css`** (design tokens under `:root`).

Page-specific layout:

- `css/landing.css` — marketing home
- `css/auth.css` — login, pricing, checkout, verify email
- `css/app.css` — dashboard & admin

After changing assets, rebuild or redeploy the frontend Docker image so `css/`, `js/`, and `assets/` are copied into nginx.
