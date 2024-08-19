# Flask Application Deployment with HTTPS on GCP

This guide covers the deployment of a Flask web application on a Google Cloud Platform (GCP) VM instance, including the setup of a wildcard HTTPS certificate using Let's Encrypt.

## Table of Contents

- [1. Domain Setup](#1-domain-setup)
- [2. Obtaining a Wildcard SSL Certificate](#2-obtaining-a-wildcard-ssl-certificate)
- [3. Web Server Configuration](#3-web-server-configuration)
- [4. Flask Application Adjustments](#4-flask-application-adjustments)
- [5. Auto-Renewal of SSL Certificate](#5-auto-renewal-of-ssl-certificate)

## 1. Domain Setup

Before starting, ensure you have a domain name pointing to your VM's IP address. This is essential for SSL/TLS certificate issuance.

## 2. Obtaining a Wildcard SSL Certificate

We will use Let's Encrypt to obtain a free SSL certificate.

### Steps:

1. **SSH into your VM**:
   Access your VM instance via SSH.

2. **Install Certbot**:
   Certbot automates the process of obtaining and renewing Let's Encrypt certificates.

```bash
sudo apt-get update
sudo apt-get install certbot
```

3. **Run Certbot with DNS Validation:**:
   Use the following command to start the process. Replace yourdomain.com with your actual domain name.

```bash
sudo certbot certonly --standalone -d yourdomain.com -d www.yourdomain.com
```

Add the provided TXT record to your DNS configuration.

4. **Complete the Validation Process:**:
   Once DNS propagation is complete, continue with Certbot to generate your wildcard certificate.

## 3. Web Server Configuration

Configure Nginx or Apache as a reverse proxy to serve your Flask application over HTTPS.

### Example with Nginx:

1. **Install Nginx:**:

```bash
sudo apt-get install nginx
```

2. **Configure Nginx:**:

- Create a new configuration file for your site in /etc/nginx/sites-available/ and symlink it to /etc/nginx/sites-enabled/.
- Edit the configuration to reverse proxy requests to your Flask app and to use the SSL certificates. Here's a basic example:
- Replace yourdomain.com, www.yourdomain.com, and your_flask_port with your actual domain name and Flask port number.

```
server {
   listen 80;
   server_name yourdomain.com www.yourdomain.com;
   return 301 https://$host$request_uri;
}

server {
   listen 443 ssl;
   server_name yourdomain.com www.yourdomain.com;

   ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
   ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

   location / {
      proxy_pass http://localhost:your_flask_port;
      proxy_set_header Host $host;
      proxy_set_header X-Real-IP $remote_addr;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto $scheme;
   }
}
```

3. **Enable the Configuration:**:
   Symlink your site's configuration and reload Nginx.

```bash
sudo ln -s /etc/nginx/sites-available/your_site /etc/nginx/sites-enabled/
sudo nginx -t # Test configuration for syntax errors.
sudo systemctl reload nginx
```

## 4. Flask Application Adjustments

Ensure your Flask application is configured to work behind a reverse proxy and handle HTTPS traffic.
**Key Adjustments**
Use ProxyFix middleware to trust headers from the reverse proxy.
Ensure secure cookies are used.
Adjust any logic that changes behavior based on HTTP or HTTPS.

## 5. Auto-Renewal of SSL Certificate

Set up a cron job for automatic renewal of the SSL certificate.

```bash
echo "0 12 * * * /usr/bin/certbot renew --quiet" | sudo tee -a /etc/crontab > /dev/null
```

#### Currently we have issue with automatically renewing the certificate. We'll figure out a solution later.
