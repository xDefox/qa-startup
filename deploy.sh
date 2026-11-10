#!/usr/bin/env bash
# ============================================================
# WebScope — deploy.sh
# One-command deployment script for production VPS
# Usage: ./deploy.sh [--build] [--migrate] [--ssl]
# ============================================================

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_DIR="/opt/webscope"
COMPOSE_FILE="docker-compose.yml"
ENV_FILE=".env.production"
DOMAIN="demo.webscope.io"

# Flags
BUILD=false
MIGRATE=false
SETUP_SSL=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --build) BUILD=true; shift ;;
        --migrate) MIGRATE=true; shift ;;
        --ssl) SETUP_SSL=true; shift ;;
        -h|--help)
            echo "Usage: $0 [--build] [--migrate] [--ssl]"
            echo "  --build    Rebuild Docker image"
            echo "  --migrate  Run database migrations"
            echo "  --ssl      Setup/renew Let's Encrypt SSL"
            exit 0
            ;;
        *) echo -e "${RED}Unknown option: $1${NC}"; exit 1 ;;
    esac
done

# Helper functions
log() { echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
error() { echo -e "${RED}✗${NC} $1"; exit 1; }

# Check prerequisites
check_prereqs() {
    log "Checking prerequisites..."
    command -v docker >/dev/null 2>&1 || error "Docker not installed"
    command -v docker compose >/dev/null 2>&1 || error "Docker Compose not installed"
    [[ -f "$ENV_FILE" ]] || error "Environment file $ENV_FILE not found. Copy from .env.example and fill in values."
    success "Prerequisites OK"
}

# Build Docker image
build_image() {
    log "Building Docker image..."
    docker compose -f "$COMPOSE_FILE" build --pull --no-cache
    success "Image built"
}

# Deploy containers
deploy_containers() {
    log "Starting containers..."
    docker compose -f "$COMPOSE_FILE" up -d --remove-orphans
    log "Waiting for health check..."
    sleep 10
    for i in {1..30}; do
        if docker compose -f "$COMPOSE_FILE" exec -T web curl -f http://localhost:8000/healthz >/dev/null 2>&1; then
            success "Health check passed"
            return 0
        fi
        sleep 2
    done
    error "Health check failed after 60s"
}

# Run database migrations
run_migrations() {
    log "Running database migrations..."
    docker compose -f "$COMPOSE_FILE" exec -T web python -c "
from webscope.webapp.storage import Storage
from webscope.webapp.services.site_service import migrate_add_organization_id, ensure_default_organization
storage = Storage('/data/webscope.db')
migrate_add_organization_id(storage)
ensure_default_organization(storage)
print('Migrations completed')
"
    success "Migrations completed"
}

# Setup SSL with Let's Encrypt
setup_ssl() {
    log "Setting up SSL with Let's Encrypt..."
    
    # Create certbot directories
    mkdir -p /var/www/certbot /var/www/html
    
    # Stop nginx temporarily if running
    systemctl stop nginx 2>/dev/null || true
    
    # Obtain certificate
    certbot certonly --standalone \
        --non-interactive \
        --agree-tos \
        --email admin@webscope.io \
        -d demo.webscope.io \
        --preferred-challenges http \
        --http-01-port 80 \
        --keep-until-expiring
    
    # Setup auto-renewal
    systemctl enable certbot.timer
    systemctl start certbot.timer
    
    success "SSL certificate obtained and auto-renewal configured"
}

# Reload nginx
reload_nginx() {
    log "Reloading nginx..."
    nginx -t && systemctl reload nginx
    success "Nginx reloaded"
}

# Show status
show_status() {
    log "Deployment status:"
    docker compose -f "$COMPOSE_FILE" ps
    echo
    log "Health check: https://demo.webscope.io/healthz"
    log "Application: https://demo.webscope.io"
    log "Landing page: https://demo.webscope.io/landing"
}

# Main deployment flow
main() {
    log "=== WebScope Deployment Started ==="
    log "Domain: $DOMAIN"
    log "Project dir: $PROJECT_DIR"
    echo
    
    check_prereqs
    
    cd "$PROJECT_DIR"
    
    if [[ "$BUILD" == true ]]; then
        build_image
    fi
    
    deploy_containers
    
    if [[ "$MIGRATE" == true ]]; then
        run_migrations
    fi
    
    if [[ "$SETUP_SSL" == true ]]; then
        setup_ssl
        reload_nginx
    fi
    
    show_status
    success "=== Deployment Completed Successfully ==="
}

# Run main
main "$@"