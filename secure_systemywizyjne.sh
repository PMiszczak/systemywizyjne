#!/bin/bash
set -e

DOMAIN="systemywizyjne.pawelmiszczak.pl"
NGINX_CONF="/etc/nginx/sites-available/flask-api"

sudo sed -i "s/server_name _;/server_name ${DOMAIN};/" "$NGINX_CONF"

sudo nginx -t
sudo systemctl reload nginx

sudo apt-get update
sudo apt-get install -y certbot python3-certbot-nginx

sudo certbot --nginx -d "$DOMAIN"

sudo systemctl enable certbot.timer
sudo systemctl start certbot.timer

echo "Gotowe."
