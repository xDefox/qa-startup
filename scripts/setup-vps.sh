#!/usr/bin/env bash
# ============================================================
# WebScope — setup-vps.sh
# One-time VPS preparation for WebScope deployment
# Run as root on fresh Ubuntu 22.04/24.04 VPS
# ============================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
error() { echo -e "${RED}✗${NC} $1"; exit 1; }

# Check root
[[ $EUID -eq 0 ]] || error "Run as root: sudo ./scripts/setup-vps.sh"

log "=== WebScope VPS Setup Started ==="
echo

# 1. System update
log "Updating system packages..."
apt-get update && apt-get upgrade -y
success "System updated"

# 2. Install base packages
log "Installing base packages..."
apt-get install -y \
    curl \
    wget \
    git \
    vim \
    htop \
    ufw \
    fail2ban \
    certbot \
    nginx \
    docker.io \
    docker-compose-plugin \
    python3 \
    python3-pip \
    python3-venv \
    jq \
    unzip
success "Base packages installed"

# 3. Install Docker (official repo for latest)
log "Setting up Docker..."
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable docker
systemctl start docker
success "Docker installed"

# 4. Install Playwright system dependencies (for Chromium in container)
log "Installing Playwright system dependencies..."
# The container has its own Playwright, but host needs deps for playwright install-deps
# Actually, the Microsoft Playwright image includes all deps. Skip host deps.
# But install for host-side playwright if needed for local testing:
# npx playwright install-deps chromium
success "Playwright deps handled in container"

# 5. Create webscope user
log "Creating webscope user..."
id -u webscope &>/dev/null || useradd -r -s /bin/bash -d /opt/webscope -m webscope
usermod -aG docker webscope
success "User 'webscope' created and added to docker group"

# 6. Create project directory
log "Setting up project directory..."
mkdir -p /opt/webscope
chown -R webscope:webscope /opt/webscope
success "Project directory ready at /opt/webscope"

# 7. Configure UFW firewall
log "Configuring firewall..."
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'
# Allow Docker internal network
ufw allow from 172.17.0.0/16
ufw --force enable
success "Firewall configured"

# 8. Configure fail2ban
log "Configuring fail2ban..."
cat > /etc/fail2ban/jail.local <<'EOF'
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5
backend = systemd

[sshd]
enabled = true
port = ssh
filter = sshd
logpath = %(sshd_log)s
maxretry = 3

[nginx-http-auth]
enabled = true
filter = nginx-http-auth
port = http,https
logpath = /var/log/nginx/error.log

[nginx-limit-req]
enabled = true
filter = nginx-limit-req
port = http,https
logpath = /var/log/nginx/error.log
maxretry = 10
EOF
systemctl enable fail2ban
systemctl restart fail2ban
success "fail2ban configured"

# 9. Configure nginx
log "Configuring nginx..."
mkdir -p /var/www/html /var/www/certbot
chown -R www-data:www-data /var/www/html /var/www/certbot

# Remove default site
rm -f /etc/nginx/sites-enabled/default

# Copy our nginx config (will be deployed with app)
# For now, create minimal config for ACME challenge
cat > /etc/nginx/sites-available/webscope <<'EOF'
server {
    listen 80;
    listen [::]:80;
    server_name demo.webscope.io;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
        try_files $uri =404;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}
EOF
ln -sf /etc/nginx/sites-available/webscope /etc/nginx/sites-enabled/webscope
nginx -t && systemctl reload nginx
systemctl enable nginx
success "Nginx configured"

# 10. Setup log rotation
log "Configuring log rotation..."
cat > /etc/logrotate.d/webscope <<'EOF'
/var/log/nginx/webscope_*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 www-data adm
    sharedscripts
    postrotate
        [ -f /var/run/nginx.pid ] && kill -USR1 `cat /var/run/nginx.pid`
    endscript
}

/var/log/webscope/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 0640 webscope webscope
}
EOF
success "Log rotation configured"

# 11. Create systemd service for docker-compose (optional, for auto-start)
log "Creating systemd service for auto-start..."
cat > /etc/systemd/system/webscope.service <<'EOF'
[Unit]
Description=WebScope Application
Requires=docker.service
After=docker.service network.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/webscope
ExecStart=/usr/bin/docker compose -f /opt/webscope/docker-compose.yml up -d
ExecStop=/usr/bin/docker compose -f /opt/webscope/docker-compose.yml down
TimeoutStartSec=120
User=webscope
Group=webscope

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable webscope.service
success "Systemd service created and enabled"

# 12. Create certbot renewal hook for nginx reload
log "Setting up certbot renewal hook..."
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx <<'EOF'
#!/bin/bash
systemctl reload nginx
EOF
chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx
success "Certbot renewal hook configured"

# 13. Setup automatic updates (security only)
log "Configuring unattended upgrades..."
apt-get install -y unattended-upgrades
cat > /etc/apt/apt.conf.d/50unattended-upgrades <<'EOF'
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}-security";
    "${distro_id}:${distro_codename}-updates";
};
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
EOF
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "7";
EOF
systemctl enable unattended-upgrades
success "Unattended upgrades configured"

# 14. Create swap file (if not exists, for memory safety)
if [[ ! -f /swapfile ]]; then
    log "Creating 2GB swap file..."
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    success "Swap file created (2GB)"
else
    warn "Swap file already exists"
fi

# 15. Final summary
echo
success "=== VPS Setup Completed Successfully ==="
echo
log "Next steps:"
echo "  1. Clone repository to /opt/webscope:"
echo "     cd /opt/webscope && git clone <your-repo> ."
echo "  2. Copy .env.example to .env.production and fill values:"
echo "     cp .env.example .env.production"
echo "  3. Run deployment:"
echo "     ./deploy.sh --build --migrate --ssl"
echo
log "Useful commands:"
echo "  - Check status:  systemctl status webscope"
echo "  - View logs:     docker compose -f /opt/webscope/docker-compose.yml logs -f"
echo "  - Restart:       systemctl restart webscope"
echo "  - SSL renew:     certbot renew --dry-run"
echo
warn "IMPORTANT: Configure DNS A-record for demo.webscope.io → $(curl -s ifconfig.me)"
warn "IMPORTANT: Add SSH key for 'webscope' user for deployment access"