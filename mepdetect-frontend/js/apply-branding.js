(function () {
    function applyBrand() {
        var b = window.MEP_BRAND;
        if (!b) return;

        if (b.faviconUrl) {
            var link = document.querySelector('link[rel="icon"]') || document.createElement('link');
            link.rel = 'icon';
            link.href = b.faviconUrl;
            if (!link.parentNode) document.head.appendChild(link);
        }

        document.querySelectorAll('[data-mep-brand]').forEach(function (el) {
            var size = el.getAttribute('data-mep-brand-size') === 'lg' ? b.logoHeightLg : b.logoHeight;
            var href = el.getAttribute('data-mep-brand-href') || b.homeUrl;
            var wrap = document.createElement('a');
            wrap.href = href;
            wrap.className = 'mep-brand-link';
            wrap.setAttribute('aria-label', b.logoAlt);

            var img = document.createElement('img');
            img.src = b.logoUrl;
            img.alt = b.logoAlt;
            img.className = 'mep-brand-img';
            img.height = size;
            img.width = 'auto';
            wrap.appendChild(img);

            if (b.showWordmark && el.getAttribute('data-mep-brand') !== 'logo-only') {
                var span = document.createElement('span');
                span.className = 'mep-brand-wordmark';
                span.textContent = b.wordmark;
                wrap.appendChild(span);
            }

            el.replaceWith(wrap);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', applyBrand);
    } else {
        applyBrand();
    }
})();
