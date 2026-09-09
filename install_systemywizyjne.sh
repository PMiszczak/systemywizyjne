#!/bin/bash
set -e

REPO_URL="https://github.com/PMiszczak/systemywizyjne.git"
PROJECT_DIR="/home/systemywizyjne"
VENV_DIR="$PROJECT_DIR/.venv"
SERVICE_NAME="flask-api"
DEPLOY_USER="${SUDO_USER:-$USER}"

echo "Instaluję i konfiguruję systemywizyjne, może to chwilę potrwać..."

sudo apt-get update
sudo apt-get upgrade -y

sudo apt-get install -y \
    git \
    python3 \
    python3-venv \
    python3-pip \
    python3-dev \
    build-essential \
    nginx \
    supervisor

sudo git clone "$REPO_URL" "$PROJECT_DIR"
sudo chown -R "$DEPLOY_USER":"$DEPLOY_USER" "$PROJECT_DIR"
sudo git config --global --add safe.directory "$PROJECT_DIR"

cd "$PROJECT_DIR"

python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip

pip install --no-cache-dir -r "$PROJECT_DIR/requirements.txt"

deactivate

# Właściciel: www-data (proces gunicorna działa jako www-data).
# Grupa: www-data, z dostępem grupowym dla DEPLOY_USER - dzięki temu administrator dalej może np. doinstalować coś w .venv bez sudo -u.
sudo chown -R www-data:www-data "$PROJECT_DIR"
sudo usermod -aG www-data "$DEPLOY_USER"
sudo chmod -R g+rwX "$PROJECT_DIR"
sudo find "$PROJECT_DIR" -type d -exec chmod g+s {} \;

sudo tee "/etc/supervisor/conf.d/${SERVICE_NAME}.conf" > /dev/null <<EOF
[program:${SERVICE_NAME}]
directory=${PROJECT_DIR}
command=${VENV_DIR}/bin/gunicorn -w 1 -b 0.0.0.0:80 app:app
autostart=true
autorestart=true
user=www-data
stdout_logfile=/var/log/${SERVICE_NAME}.out.log
stderr_logfile=/var/log/${SERVICE_NAME}.err.log
environment=PATH="${VENV_DIR}/bin"
EOF

sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl restart "$SERVICE_NAME" || true

sudo tee /etc/nginx/sites-available/flask-api > /dev/null <<'EOF'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://0.0.0.0:80;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/flask-api \
    /etc/nginx/sites-enabled/flask-api

# Usunięcie domyślnej konfiguracji Nginx
sudo rm -f /etc/nginx/sites-enabled/default

sudo nginx -t

sudo systemctl enable nginx
sudo systemctl restart nginx

echo "Gotowe."
echo "Logi: /var/log/${SERVICE_NAME}.out.log oraz .err.log"
