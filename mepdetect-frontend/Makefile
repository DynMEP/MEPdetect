# MEPdetect Landing Page - Makefile
# Quick commands for container management

.PHONY: help build start stop restart logs status health update backup clean

# Default target
help:
	@echo "MEPdetect Landing Page - Docker Management"
	@echo ""
	@echo "Available commands:"
	@echo "  make build          - Build the Docker image"
	@echo "  make start          - Start the container"
	@echo "  make stop           - Stop the container"
	@echo "  make restart        - Restart the container"
	@echo "  make logs           - Show container logs (follow mode)"
	@echo "  make status         - Show container status"
	@echo "  make health         - Run health check"
	@echo "  make update         - Update HTML content without rebuild"
	@echo "  make update-auth    - Update user management HTML files"
	@echo "  make backup         - Backup current landing page"
	@echo "  make clean          - Remove container and image"
	@echo "  make deploy         - Full deployment (build + start)"
	@echo "  make test-pages     - Test all HTML pages"
	@echo ""

# Build Docker image
build:
	@echo "Building MEPdetect landing page image..."
	docker-compose build

# Start container
start:
	@echo "Starting MEPdetect landing page..."
	docker-compose up -d

# Stop container
stop:
	@echo "Stopping MEPdetect landing page..."
	docker-compose down

# Restart container
restart: stop start
	@echo "Container restarted successfully!"

# Show logs (follow mode)
logs:
	docker logs -f mepdetect-landing

# Show last 50 log lines
logs-tail:
	docker logs --tail 50 mepdetect-landing

# Show container status
status:
	@echo "=== Container Status ==="
	@docker ps | grep mepdetect-landing || echo "Container not running"
	@echo ""
	@echo "=== Health Status ==="
	@docker inspect --format='{{.State.Health.Status}}' mepdetect-landing 2>/dev/null || echo "N/A"
	@echo ""
	@echo "=== Resource Usage ==="
	@docker stats --no-stream mepdetect-landing 2>/dev/null || echo "Container not running"

# Run health check
health:
	@echo "Running health check..."
	@curl -f http://localhost:8090/health || echo "Health check failed"
	@echo ""
	@curl -I http://localhost:8090 || echo "HTTP check failed"

# Update HTML content
update:
	@echo "Updating landing page content..."
	docker cp mepdetect-landing-page.html mepdetect-landing:/usr/share/nginx/html/index.html
	docker exec mepdetect-landing nginx -s reload
	@echo "Content updated successfully!"

# Update user management HTML files (without rebuild)
update-auth:
	@echo "Updating user management pages..."
	@docker cp login.html mepdetect-landing:/usr/share/nginx/html/login.html 2>/dev/null && echo "✓ login.html updated" || echo "✗ login.html not found"
	@docker cp dashboard.html mepdetect-landing:/usr/share/nginx/html/dashboard.html 2>/dev/null && echo "✓ dashboard.html updated" || echo "✗ dashboard.html not found"
	@docker cp admin.html mepdetect-landing:/usr/share/nginx/html/admin.html 2>/dev/null && echo "✓ admin.html updated" || echo "✗ admin.html not found"
	@docker exec mepdetect-landing nginx -s reload
	@echo "User management pages updated!"

# Test all pages
test-pages:
	@echo "Testing all HTML pages..."
	@echo "=== Landing Page ==="
	@curl -I http://localhost:8090 2>/dev/null | head -1
	@echo "=== Login Page ==="
	@curl -I http://localhost:8090/login.html 2>/dev/null | head -1
	@echo "=== Dashboard Page ==="
	@curl -I http://localhost:8090/dashboard.html 2>/dev/null | head -1
	@echo "=== Admin Page ==="
	@curl -I http://localhost:8090/admin.html 2>/dev/null | head -1

# List files in container
list-files:
	@echo "Files in container:"
	@docker exec mepdetect-landing ls -lah /usr/share/nginx/html/

# Backup current version
backup:
	@mkdir -p backups
	@docker cp mepdetect-landing:/usr/share/nginx/html/index.html backups/backup-$$(date +%Y%m%d-%H%M%S).html
	@echo "Backup created in backups/ directory"

# Clean up
clean:
	@echo "Removing container and image..."
	docker-compose down
	docker rmi mepdetector-mepdetect-landing 2>/dev/null || true
	@echo "Cleanup complete!"

# Full deployment
deploy: build start
	@echo "Deployment complete!"
	@echo "Landing page available at: http://$$(hostname -I | awk '{print $$1}'):8090"

# Quick rebuild and restart
rebuild: stop build start
	@echo "Rebuild complete!"

# View nginx configuration
config:
	@docker exec mepdetect-landing cat /etc/nginx/conf.d/nginx.conf

# Test nginx configuration
test-config:
	@docker exec mepdetect-landing nginx -t

# Access container shell
shell:
	docker exec -it mepdetect-landing sh

# View access logs
access-logs:
	docker exec mepdetect-landing cat /var/log/nginx/mepdetect_access.log 2>/dev/null || docker exec mepdetect-landing cat /var/log/nginx/access.log

# View error logs
error-logs:
	docker exec mepdetect-landing cat /var/log/nginx/mepdetect_error.log 2>/dev/null || docker exec mepdetect-landing cat /var/log/nginx/error.log

# Monitor real-time
monitor:
	watch -n 2 'docker stats --no-stream mepdetect-landing'