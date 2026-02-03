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

Sudo Permissions: If you're using sudo in a cron job, ensure that the user running the cron job has the necessary permissions to execute these commands without being prompted for a password. You can configure this in the /etc/sudoers file by adding a line like:

```bash
alex123bobo ALL=(ALL) NOPASSWD: /usr/bin/certbot renew, /bin/systemctl stop nginx, /bin/systemctl start nginx
```

#### Currently we have issue with automatically renewing the certificate. We'll figure out a solution later.

---

# AI Service - Modular Architecture

This Flask application now includes a comprehensive AI service with a modular architecture for dictionary lookups, chat functionality, audio transcription, and vision analysis.

## Features

### 1. **Dictionary Agent**
- **DeepSeek Integration**: Uses DeepSeek LLM via Agno framework
- **Enhanced Schema**: Comprehensive dictionary entries with multiple senses
- **JSON Mode**: Structured responses using Pydantic models
- **Modular Design**: Separate schemas and prompts modules

### 2. **OpenAI Integration**
- **Audio Transcription**: Transcribe audio files to text
- **Vision Analysis**: Analyze images and extract information

### 3. **Modular Architecture**
- **Schemas Module**: Centralized Pydantic models for type safety
- **Prompts Module**: Reusable prompt templates with variable substitution
- **Agents Module**: AI agents using schemas and prompts

## API Endpoints

### Dictionary Endpoints
- `GET /api/dictionary/test` - Test endpoint
- `POST /api/dictionary` - Look up a word (requires JSON with "word" field)

### OpenAI Endpoints
- `GET /api/transcribe` - Audio transcription form
- `POST /api/transcribe` - Transcribe audio file
- `GET /api/vision` - Vision analysis form
- `POST /api/vision` - Analyze image file

## Getting Started

### 1. Installation
```bash
# Clone the repository
git clone <repository-url>
cd PP-AI-Service

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration
Create a `.env` file with:
```env
DEEPSEEK_API_KEY=your_deepseek_api_key
OPENAI_API_KEY=your_openai_api_key
```

### 3. Running the Service
```bash
# Start Flask server
source venv/bin/activate
python app.py

# Run tests
python test_all_features.py
python test_endpoint.py
```

## Architecture Documentation

For detailed architecture documentation, see [MODULAR_ARCHITECTURE.md](MODULAR_ARCHITECTURE.md).

## Key Benefits

1. **Maintainability**: Centralized schemas and prompts
2. **Extensibility**: Easy to add new agent types
3. **Type Safety**: Pydantic models with validation
4. **Consistency**: Standardized prompt templates
5. **Backward Compatibility**: Old endpoints still work

## Future Extensions

- Add more agent types (grammar, translation, summarization)
- Implement caching for frequent requests
- Add rate limiting and metrics
- Support for more LLM providers
