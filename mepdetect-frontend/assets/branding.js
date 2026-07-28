/**
 * MEPdetect — single place to change logo & brand name across all pages.
 *
 * 1. Replace /assets/logo.svg with your image (or set logoUrl to .png / full URL).
 * 2. Set showWordmark: false if the image already includes the name.
 * 3. Every page loads this file; slots marked data-mep-brand get the logo automatically.
 */
window.MEP_BRAND = {
    logoUrl: '/assets/logo.svg?v=2',
    logoAlt: 'MEPdetect',
    wordmark: 'MEPdetect',
    homeUrl: '/',
    /** Height in px for header / sidebar logos */
    logoHeight: 32,
    /** Taller variant for auth panels */
    logoHeightLg: 40,
    showWordmark: true,
    /** Favicon (optional) — add file and uncomment */
    // faviconUrl: '/assets/favicon.ico',
};
