# MEPdetect Landing Page - Dockerfile
FROM nginx:alpine

# Install curl for healthcheck
RUN apk add --no-cache curl

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Copy custom nginx configuration
COPY nginx.conf /etc/nginx/conf.d/

# Copy landing page files
COPY mepdetect-landing-page.html /usr/share/nginx/html/index.html

# Copy user management HTML files
COPY login.html /usr/share/nginx/html/login.html
COPY dashboard.html /usr/share/nginx/html/dashboard.html
COPY admin.html /usr/share/nginx/html/admin.html
COPY verify-email.html /usr/share/nginx/html/verify-email.html
COPY pricing.html /usr/share/nginx/html/pricing.html
COPY checkout.html /usr/share/nginx/html/checkout.html
COPY 404.html /usr/share/nginx/html/404.html

# Legal pages, served at /privacy and /terms
COPY privacy.html /usr/share/nginx/html/privacy.html
COPY terms.html /usr/share/nginx/html/terms.html

# Shared theme, branding, assets
COPY css/ /usr/share/nginx/html/css/
COPY js/ /usr/share/nginx/html/js/
COPY assets/ /usr/share/nginx/html/assets/

# Substitute the reCAPTCHA site key at start-up. nginx's entrypoint runs the
# executable scripts in this directory before the server accepts requests, so
# pages are served with the key already in place. chmod here rather than rely
# on the checked-in file mode, which does not survive every platform.
COPY docker-entrypoint.d/ /docker-entrypoint.d/
RUN chmod +x /docker-entrypoint.d/*.sh

# Set proper permissions
RUN chown -R nginx:nginx /usr/share/nginx/html && \
    chmod -R 755 /usr/share/nginx/html

# Expose port 80
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost/health || exit 1

# Start nginx
CMD ["nginx", "-g", "daemon off;"]