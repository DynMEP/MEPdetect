#!/bin/bash

# MEPdetect Landing Page - Deployment Script
# Usage: ./deploy.sh [start|stop|restart|logs|status|update]

set -e

CONTAINER_NAME="mepdetect-landing"
COMPOSE_FILE="docker-compose.yml"
PORT=8090

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker is installed
check_docker() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null; then
        log_error "Docker Compose is not installed. Please install Docker Compose first."
        exit 1
    fi
}

# Check if required files exist
check_files() {
    local missing_files=()
    
    if [ ! -f "Dockerfile" ]; then
        missing_files+=("Dockerfile")
    fi
    
    if [ ! -f "docker-compose.yml" ]; then
        missing_files+=("docker-compose.yml")
    fi
    
    if [ ! -f "nginx.conf" ]; then
        missing_files+=("nginx.conf")
    fi
    
    if [ ! -f "mepdetect-landing-page.html" ]; then
        missing_files+=("mepdetect-landing-page.html")
    fi
    
    if [ ${#missing_files[@]} -ne 0 ]; then
        log_error "Missing required files: ${missing_files[*]}"
        exit 1
    fi
}

# Start the container
start_container() {
    log_info "Starting MEPdetect landing page..."
    
    if docker ps -a | grep -q $CONTAINER_NAME; then
        log_warn "Container already exists. Stopping and removing..."
        docker-compose down
    fi
    
    log_info "Building and starting container..."
    docker-compose up -d --build
    
    log_info "Waiting for container to be healthy..."
    sleep 5
    
    if docker ps | grep -q $CONTAINER_NAME; then
        log_info "Container started successfully!"
        log_info "Landing page available at: http://$(hostname -I | awk '{print $1}'):${PORT}"
        show_status
    else
        log_error "Failed to start container. Check logs with: docker logs $CONTAINER_NAME"
        exit 1
    fi
}

# Stop the container
stop_container() {
    log_info "Stopping MEPdetect landing page..."
    
    if ! docker ps | grep -q $CONTAINER_NAME; then
        log_warn "Container is not running."
        return
    fi
    
    docker-compose down
    log_info "Container stopped successfully!"
}

# Restart the container
restart_container() {
    log_info "Restarting MEPdetect landing page..."
    stop_container
    sleep 2
    start_container
}

# Show logs
show_logs() {
    local lines=${1:-50}
    
    if ! docker ps | grep -q $CONTAINER_NAME; then
        log_error "Container is not running."
        exit 1
    fi
    
    log_info "Showing last $lines lines of logs (Ctrl+C to exit)..."
    docker logs --tail $lines -f $CONTAINER_NAME
}

# Show container status
show_status() {
    log_info "MEPdetect Landing Page Status:"
    echo ""
    
    if docker ps | grep -q $CONTAINER_NAME; then
        echo "Status: $(docker inspect --format='{{.State.Status}}' $CONTAINER_NAME)"
        echo "Health: $(docker inspect --format='{{.State.Health.Status}}' $CONTAINER_NAME 2>/dev/null || echo 'N/A')"
        echo "Uptime: $(docker inspect --format='{{.State.StartedAt}}' $CONTAINER_NAME)"
        echo ""
        
        # Port mappings
        echo "Port Mappings:"
        docker port $CONTAINER_NAME
        echo ""
        
        # Resource usage
        echo "Resource Usage:"
        docker stats --no-stream $CONTAINER_NAME
        echo ""
        
        # Quick HTTP test
        echo "HTTP Test:"
        if curl -s -o /dev/null -w "%{http_code}" http://localhost:${PORT} | grep -q "200"; then
            log_info "HTTP test passed - page is accessible"
        else
            log_error "HTTP test failed - page may not be accessible"
        fi
    else
        log_warn "Container is not running."
        
        if docker ps -a | grep -q $CONTAINER_NAME; then
            echo "Container exists but is stopped."
            echo "Use './deploy.sh start' to start it."
        else
            echo "Container does not exist."
            echo "Use './deploy.sh start' to create and start it."
        fi
    fi
}

# Update landing page content
update_content() {
    log_info "Updating landing page content..."
    
    if [ ! -f "mepdetect-landing-page.html" ]; then
        log_error "mepdetect-landing-page.html not found!"
        exit 1
    fi
    
    if ! docker ps | grep -q $CONTAINER_NAME; then
        log_error "Container is not running. Start it first with './deploy.sh start'"
        exit 1
    fi
    
    # Copy new HTML file to container
    docker cp mepdetect-landing-page.html ${CONTAINER_NAME}:/usr/share/nginx/html/index.html
    
    # Reload nginx
    docker exec $CONTAINER_NAME nginx -s reload
    
    log_info "Content updated successfully!"
}

# Run health check
health_check() {
    log_info "Running comprehensive health check..."
    echo ""
    
    # Container status
    echo "1. Container Status:"
    if docker ps | grep -q $CONTAINER_NAME; then
        echo "   ✓ Container is running"
    else
        echo "   ✗ Container is not running"
        return 1
    fi
    
    # Health status
    echo "2. Health Check:"
    local health=$(docker inspect --format='{{.State.Health.Status}}' $CONTAINER_NAME 2>/dev/null)
    if [ "$health" = "healthy" ]; then
        echo "   ✓ Container is healthy"
    else
        echo "   ✗ Container health: $health"
    fi
    
    # HTTP endpoint
    echo "3. HTTP Endpoint:"
    local http_code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:${PORT})
    if [ "$http_code" = "200" ]; then
        echo "   ✓ HTTP endpoint responding (200 OK)"
    else
        echo "   ✗ HTTP endpoint returned: $http_code"
    fi
    
    # Health endpoint
    echo "4. Health Endpoint:"
    if curl -sf http://localhost:${PORT}/health > /dev/null; then
        echo "   ✓ Health endpoint responding"
    else
        echo "   ✗ Health endpoint not responding"
    fi
    
    # Nginx config
    echo "5. Nginx Configuration:"
    if docker exec $CONTAINER_NAME nginx -t 2>&1 | grep -q "successful"; then
        echo "   ✓ Nginx configuration is valid"
    else
        echo "   ✗ Nginx configuration has errors"
    fi
    
    # Recent errors
    echo "6. Recent Errors:"
    local error_count=$(docker logs --since 1h $CONTAINER_NAME 2>&1 | grep -i error | wc -l)
    if [ $error_count -eq 0 ]; then
        echo "   ✓ No errors in last hour"
    else
        echo "   ⚠ Found $error_count errors in last hour"
        echo "   Run './deploy.sh logs' to view details"
    fi
    
    echo ""
    log_info "Health check complete!"
}

# Backup current version
backup() {
    local backup_dir="backups"
    local timestamp=$(date +%Y%m%d_%H%M%S)
    
    log_info "Creating backup..."
    
    mkdir -p $backup_dir
    
    if docker ps | grep -q $CONTAINER_NAME; then
        docker cp ${CONTAINER_NAME}:/usr/share/nginx/html/index.html \
            ${backup_dir}/mepdetect-landing-${timestamp}.html
        log_info "Backup saved to: ${backup_dir}/mepdetect-landing-${timestamp}.html"
    else
        if [ -f "mepdetect-landing-page.html" ]; then
            cp mepdetect-landing-page.html ${backup_dir}/mepdetect-landing-${timestamp}.html
            log_info "Backup saved to: ${backup_dir}/mepdetect-landing-${timestamp}.html"
        else
            log_error "No file to backup!"
            exit 1
        fi
    fi
}

# Show usage
show_usage() {
    cat << EOF
MEPdetect Landing Page - Deployment Script

Usage: ./deploy.sh [COMMAND]

Commands:
    start       Start the landing page container
    stop        Stop the landing page container
    restart     Restart the landing page container
    logs        Show container logs (default: last 50 lines)
    status      Show container status and health
    update      Update landing page content without rebuild
    health      Run comprehensive health check
    backup      Backup current landing page
    help        Show this help message

Examples:
    ./deploy.sh start           # Start the container
    ./deploy.sh logs 100        # Show last 100 log lines
    ./deploy.sh status          # Check status
    ./deploy.sh update          # Update content only

EOF
}

# Main script
main() {
    local command=${1:-help}
    
    case $command in
        start)
            check_docker
            check_files
            start_container
            ;;
        stop)
            check_docker
            stop_container
            ;;
        restart)
            check_docker
            check_files
            restart_container
            ;;
        logs)
            check_docker
            show_logs ${2:-50}
            ;;
        status)
            check_docker
            show_status
            ;;
        update)
            check_docker
            update_content
            ;;
        health)
            check_docker
            health_check
            ;;
        backup)
            backup
            ;;
        help|--help|-h)
            show_usage
            ;;
        *)
            log_error "Unknown command: $command"
            echo ""
            show_usage
            exit 1
            ;;
    esac
}

# Run main function
main "$@"
