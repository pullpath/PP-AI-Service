# TOS Storage Deployment Guide

This document provides critical deployment tips for PP-AI-Service with TOS (Volcengine Object Storage) integration, focusing on crcmod configuration, multi-process safety, and performance optimization for video uploads.

## Table of Contents

- [1. TOS Storage and crcmod Configuration](#1-tos-storage-and-crcmod-configuration)
- [2. Environment Setup](#2-environment-setup)
- [3. Multi-Process Safety](#3-multi-process-safety)
- [4. Docker Deployment](#4-docker-deployment)
- [5. Performance Monitoring](#5-performance-monitoring)

---

## 1. TOS Storage and crcmod Configuration

### Why This Matters

The TOS (Tencent Object Storage) Python SDK depends on `crcmod` for CRC64 checksum calculations during file uploads/downloads. If `crcmod` runs in pure Python mode instead of C extension mode, **performance can be 100x slower**, causing video uploads to time out or take minutes instead of seconds.

### 🔴 Critical: Install python3-dev BEFORE pip install

#### On Debian/Ubuntu (Google Cloud, AWS, DigitalOcean)

```bash
# 1. Install python3-dev FIRST
sudo apt-get update
sudo apt-get install python3-dev

# 2. Then install Python dependencies
pip install -r requirements.txt
```

#### On CentOS/RHEL/Fedora

```bash
# Python 3.x
sudo yum install python3-devel

# Then install dependencies
pip install -r requirements.txt
```

#### On Windows/macOS

Python development headers are included by default with the Python installer. No additional steps needed.

### ✅ Verify crcmod C Extension Installation

After installing dependencies, verify that `crcmod` compiled successfully:

```bash
# Test C extension
python3 -c "import crcmod._crcfunext; print('✅ crcmod C extension installed successfully')"
```

**Expected output**: `✅ crcmod C extension installed successfully`

**If you see an error** (`ImportError: No module named _crcfunext`):

```bash
# Fix the issue
pip uninstall crcmod
sudo apt-get install python3-dev  # Ensure this is installed
pip install --no-cache-dir crcmod  # Force recompile
```

### Technical Background

**Why python3-dev is required:**
- `crcmod` has two modes: **pure Python** and **C extension**
- The C extension depends on `Python.h` header file (provided by `python3-dev`)
- Without `Python.h`, `crcmod` silently falls back to pure Python mode
- Pure Python CRC calculation is ~100x slower than C extension

**Impact on video uploads:**
- C extension mode: 2-5 seconds for typical video
- Pure Python mode: 3-5 minutes for same video (may timeout)

---

## 2. Environment Setup

### Required Environment Variables

Create a `.env` file with all necessary credentials:

```env
# TOS Storage (required for video uploads)
TOS_ACCESS_KEY=your_tos_access_key
TOS_SECRET_KEY=your_tos_secret_key

# Dictionary Service
DEEPSEEK_API_KEY=your_deepseek_api_key

# AI Video Generation (optional)
ARK_API_KEY=your_volcengine_api_key

# OpenAI Services
OPENAI_API_KEY=your_openai_api_key
OPENAI_API_BASE=your_proxy_url  # Optional
X-PP-TOKEN=your_proxy_token     # Optional

# Bilibili API (optional)
BILIBILI_SESSDATA=your_sessdata_cookie
BILIBILI_BILI_JCT=your_bili_jct_cookie
BILIBILI_BUVID3=your_buvid3_cookie

# Web Services
SERPER_API_KEY=your_serper_api_key
BROWSERLESS_API_KEY=your_browserless_api_key

# Flask
FLASK_ENV=production
```

### Systemd Service Configuration

For production deployment with systemd (recommended):

```ini
# /etc/systemd/system/ppai.service
[Unit]
Description=PP-AI-Service Flask Application
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/PP-AI-Service
EnvironmentFile=/path/to/.env
ExecStart=/path/to/venv/bin/python app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable ppai.service
sudo systemctl start ppai.service
sudo systemctl status ppai.service
```

---

## 3. Multi-Process Safety

### TOS Client Management

**IMPORTANT**: The TOS SDK documentation explicitly warns about multi-process safety:

> **多进程场景下需要创建多个 TosClient，不能共享同一个 TosClient，否则会有多进程并发安全问题，可能会导致读写请求数据错乱。**
> 
> (In multi-process scenarios, you must create multiple TosClient instances. Do NOT share a single TosClient, or you will have concurrency safety issues that may cause data corruption.)

### ✅ Current Implementation (Correct)

The codebase already follows best practices:

```python
# Each operation creates and closes its own client
def put_object(bucket_name: str, object_key: str, data: Any):
    client = tos.TosClientV2(access_key, secret_key, endpoint, region)
    client.put_object(bucket_name, object_key, content=data)
    client.close()  # Clean up
    return True
```

**Why this is safe:**
- Each request gets a fresh TosClient instance
- No client sharing across processes/threads
- Explicit cleanup with `client.close()`
- Safe for Gunicorn/uWSGI with multiple workers

### ❌ Anti-Pattern (DO NOT DO THIS)

```python
# WRONG: Shared global client
client = tos.TosClientV2(access_key, secret_key, endpoint, region)

def put_object(bucket_name: str, object_key: str, data: Any):
    client.put_object(bucket_name, object_key, content=data)  # Data corruption risk!
```

This will cause data corruption with multiple workers.

---

## 4. Docker Deployment

### Update Dockerfile for crcmod Support

Ensure your Dockerfile includes `python3-dev` and build tools:

```dockerfile
FROM python:3.10.13-slim

# Install system dependencies including python3-dev for crcmod C extension
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3-dev \
        gcc \
        build-essential && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Verify crcmod C extension installed correctly
RUN python -c "import crcmod._crcfunext" || \
    (echo "ERROR: crcmod C extension not installed!" && exit 1)

# Copy application code
COPY . .

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app && \
    mkdir -p /app/static/uploads && \
    chown -R appuser:appuser /app/static/uploads

USER appuser

# Expose port
EXPOSE 8000

# Run application
CMD ["python", "app.py"]
```

**Key changes:**
1. Install `python3-dev`, `gcc`, `build-essential` for compiling C extensions
2. Add verification step to ensure `crcmod` C extension works
3. Docker build will fail early if `crcmod` doesn't compile

### Build and Test

```bash
# Build with verification
docker build . -t pp-ai-service

# If build succeeds, crcmod is working correctly
docker run --rm -p 8000:8000 --env-file .env pp-ai-service
```

---

## 5. Performance Monitoring

### Disable CRC64 Verification (If Needed)

If uploads/downloads are still slow even with C extension:

```python
# In ai_svc/dictionary/tos_storage.py
client = tos.TosClientV2(
    access_key, 
    secret_key, 
    endpoint, 
    region,
    enable_crc=False  # Disable CRC64 verification
)
```

**Trade-off**: Disabling CRC sacrifices data integrity checks for speed. Only do this if performance is critical and you have other verification mechanisms.

### Monitor Upload Performance

Add timing logs to track performance:

```python
import time

def download_and_upload_video(...):
    start_time = time.time()
    
    # ... existing code ...
    
    upload_duration = time.time() - start_time
    logger.info(f"Video upload completed in {upload_duration:.2f}s")
    
    if upload_duration > 10:
        logger.warning(f"Slow upload detected: {upload_duration:.2f}s - check crcmod installation")
```

**Expected performance:**
- With C extension: 2-5 seconds for typical video (5-10 MB)
- Pure Python mode: 30+ seconds (red flag)

---

## Deployment Checklist

Before deploying to production:

- [ ] **Install `python3-dev`** via package manager
- [ ] **Verify crcmod C extension**: `python3 -c "import crcmod._crcfunext"`
- [ ] **Set all environment variables** in `.env` or systemd service
- [ ] **Test TOS upload** with a sample video
- [ ] **Monitor upload performance** (should be <5s for typical videos)
- [ ] **Configure Nginx reverse proxy** (see [DEPLOYMENT.md](DEPLOYMENT.md))
- [ ] **Set up SSL/HTTPS** with Let's Encrypt
- [ ] **Enable systemd service** for auto-restart
- [ ] **Configure log rotation** for `~/ppaiservice.log`
- [ ] **Set up monitoring** for API errors and performance metrics

---

## Common Issues

### Issue: Video uploads timing out

**Diagnosis:**
```bash
# Check if crcmod C extension is working
python3 -c "import crcmod._crcfunext"
```

**Solution:**
```bash
pip uninstall crcmod
sudo apt-get install python3-dev
pip install --no-cache-dir crcmod
```

### Issue: "TOS credentials not configured"

**Diagnosis:**
Check environment variables are loaded:
```bash
echo $TOS_ACCESS_KEY
echo $TOS_SECRET_KEY
```

**Solution:**
Ensure `.env` file exists and is loaded, or set variables in systemd service file.

### Issue: Data corruption with multiple workers

**Diagnosis:**
Check if using shared TosClient instance.

**Solution:**
Create new `TosClientV2` instance for each operation (already implemented correctly in codebase).

### Issue: Access Denied (403) on Video URLs

**Symptoms:**
Videos return "Access Denied" error when accessing via public URL:
```json
{
  "Code": "AccessDenied",
  "Message": "Access Denied",
  "EC": "0003-00000015"
}
```

**Cause:**
Objects were uploaded with `ACL_Private` (default) instead of `ACL_Public_Read`.

**Solution Option 1 - Automated Fix (Recommended):**
```bash
cd /Users/jiali/personal_github_repos/PP-AI-Service
source venv/bin/activate
python fix_tos_acl.py
```

This script will:
- Set bucket ACL to Public Read
- Set all existing video objects to Public Read
- Verify public access works

**Solution Option 2 - Manual Fix (TOS Console):**
1. Go to [TOS Console](https://console.volcengine.com/tos)
2. Select bucket: `video-bucket-for-ai-generated-phrase-usage`
3. Settings → Access Permissions → Edit → Public Read
4. For each video: Right-click → Permissions → Public Read

**Solution Option 3 - Re-upload:**
Since the code now uses `ACL_Public_Read` by default:
1. Delete existing videos from TOS
2. Generate new videos (will auto-upload with Public Read)

**Verification:**
```bash
# Test a video URL
curl -I https://{bucket}.tos-cn-beijing.volces.com/hello/pipe-down/1710554231.mp4

# Expected: HTTP/2 200
# If you get 403, the fix didn't work
```

**Security Note:**
Public Read is safe for this use case because:
- Educational content only (no sensitive data)
- Public dictionary service (no authentication required)
- Videos demonstrate English phrases (safe for all audiences)
- Write/delete access remains protected (only you can modify)

---

## References

- [TOS Python SDK Documentation](https://www.volcengine.com/docs/6349/74850)
- [crcmod PyPI Package](https://pypi.org/project/crcmod/)
- [DEPLOYMENT.md](DEPLOYMENT.md) - General deployment guide
- [AGENTS.md](../AGENTS.md) - Codebase architecture

---

**Last Updated**: March 16, 2026
