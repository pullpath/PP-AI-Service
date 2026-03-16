# TOS Storage Integration for AI Video Generation

## Overview

This document describes the TOS (Volcengine Object Storage) integration for permanently storing AI-generated phrase videos. The integration automatically uploads videos to cloud storage after generation to prevent loss when provider URLs expire (24 hours).

## Architecture

### Storage Structure

Videos are organized using the following path structure:

```
[word]/[phrase]/[timestamp].[ext]
```

**Example:**
```
hello/pipe-down/1710554231.mp4
goodbye/see-you-later/1710554532.mp4
```

### Components

#### 1. TOS Storage Module (`ai_svc/dictionary/tos_storage.py`)

**Functions:**

- `init_bucket(bucket_name: str)`: Creates bucket if not exists, checks existence first
- `put_object(bucket_name: str, object_key: str, data: Any)`: Uploads binary data to TOS
- `download_and_upload_video(video_url: str, word: str, phrase: str, bucket_name: Optional[str] = None)`: Main integration function

**Key Features:**

- Automatic bucket initialization
- Path sanitization (converts spaces to hyphens, removes special characters)
- File extension inference from URL
- Timestamp-based versioning
- Error handling with logging
- Graceful fallback to original URL if upload fails

#### 2. Video Task Service Integration (`ai_svc/dictionary/video_task_service.py`)

**Changes:**

1. Added `word` field to `video_tasks` table (with migration support)
2. Updated `create_task()` to accept `word` parameter
3. Modified `_generate_video_background()` to:
   - Download video from Volcengine URL
   - Upload to TOS storage
   - Use TOS URL as primary, Volcengine URL as fallback
   - Update progress tracking (70% after upload)

**Workflow:**

```
1. Generate video via Volcengine API (30% → 70%)
2. Download video from Volcengine URL
3. Upload video to TOS storage
4. Return TOS URL to frontend (70% → 100%)
5. Fallback to Volcengine URL if TOS upload fails
```

#### 3. Dictionary Service Integration (`ai_svc/dictionary/service.py`)

**Changes:**

- Pass `word` parameter to `video_task_service.create_task()`

## Configuration

### Environment Variables

Add to `.env`:

```env
# TOS Storage (required for permanent video storage)
TOS_ACCESS_KEY=your_tos_access_key
TOS_SECRET_KEY=your_tos_secret_key
BUCKET_NAME_PREFIX=your_prefix_  # Optional, defaults to empty string
```

### Bucket Naming

Default bucket name format:
```
{BUCKET_NAME_PREFIX}video-bucket-for-ai-generated-phrase-usage
```

**Example:**
- With `BUCKET_NAME_PREFIX=dev-`: `dev-video-bucket-for-ai-generated-phrase-usage`
- Without prefix: `video-bucket-for-ai-generated-phrase-usage`

## Public URL Format

Videos are accessible via:

```
https://{bucket_name}.tos-cn-beijing.volces.com/{word}/{phrase}/{timestamp}.mp4
```

**Example:**
```
https://dev-video-bucket-for-ai-generated-phrase-usage.tos-cn-beijing.volces.com/hello/pipe-down/1710554231.mp4
```

## Error Handling

### Graceful Degradation

If TOS upload fails:
1. Log warning with reason
2. Use original Volcengine URL as fallback
3. Mark task as completed (not failed)
4. Note: Volcengine URL expires in 24 hours

### Failure Scenarios

| Scenario | Behavior |
|----------|----------|
| TOS credentials missing | Skip upload, use Volcengine URL, log warning |
| Bucket creation fails | Skip upload, use Volcengine URL, log error |
| Video download fails | Fail task, log error |
| Video upload fails | Use Volcengine URL, log warning |

## Testing

### Manual Testing

```bash
# 1. Generate a video (triggers automatic TOS upload)
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{
    "word": "hello",
    "section": "ai_generated_phrase_video",
    "phrase": "pipe down"
  }'

# 2. Poll for completion
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{
    "word": "hello",
    "section": "video_status",
    "task_id": "task-id-from-step-1"
  }'

# 3. Verify video URL is from TOS (not Volcengine)
# Expected: https://{bucket}.tos-cn-beijing.volces.com/hello/pipe-down/...mp4
# Fallback: https://ark-content-generation-cn-beijing.tos-cn-beijing.volces.com/...
```

### Integration Testing

```python
from ai_svc.dictionary.tos_storage import download_and_upload_video

# Test video upload
tos_url = download_and_upload_video(
    video_url="https://example.com/video.mp4",
    word="hello",
    phrase="pipe down"
)

print(f"TOS URL: {tos_url}")
```

## Logging

### Log Messages

```
[INFO] Downloading video from https://...
[INFO] Downloaded 1234567 bytes from Volcengine
[INFO] Uploading video to TOS: hello/pipe-down/1710554231.mp4
[INFO] Video uploaded successfully to TOS: https://...
[INFO] [Task abc123] Video uploaded to TOS storage: https://...
```

### Warning Messages

```
[WARNING] [Task abc123] TOS upload failed, using Volcengine URL (will expire in 24h)
[WARNING] TOS credentials not configured - cannot upload video
```

## Performance

### Timeline

| Phase | Duration | Progress |
|-------|----------|----------|
| Video generation | 30-60s | 10% → 30% |
| Video generation (Volcengine) | Variable | 30% → 70% |
| Download video | 2-5s | 70% |
| Upload to TOS | 3-10s | 70% → 100% |
| **Total** | **35-75s** | **Complete** |

### Network Overhead

- Download: ~1-5 MB video (2-5 seconds)
- Upload: ~1-5 MB video (3-10 seconds)
- **Total overhead: 5-15 seconds**

## Migration Guide

### Database Migration

The system automatically migrates existing `video_tasks` tables:

1. Detects missing `word` column
2. Adds `word TEXT` column to table
3. Existing rows will have `NULL` for `word` (defaults to 'unknown' in code)

No manual migration needed - runs on service startup.

### Backward Compatibility

- Old videos without `word` field: Continue to work (word defaults to 'unknown')
- TOS upload failures: Gracefully fall back to Volcengine URL
- Missing TOS credentials: Skip upload, log warning, use Volcengine URL

## Security Considerations

1. **Public Bucket**: Bucket created with `ACL_Public_Read` for public dictionary access
2. **Public URLs**: Objects are publicly readable via direct URL (no authentication needed)
3. **No Expiration**: URLs don't expire (permanent storage)
4. **No Sensitive Data**: Only educational video content (safe for public access)

### Security Trade-offs

**Why Public Read ACL:**
- Dictionary is a public educational resource
- No user authentication/login system
- Videos contain no sensitive data (educational phrases only)
- Simplifies frontend (direct video URLs, no presigning needed)

**Risks:**
- Anyone with URL can access videos
- Bucket contents can be listed (if bucket listing enabled)
- No access logs by default
- No expiration/revocation mechanism

### Recommendation for Production

Consider implementing:
- **CDN Integration**: CloudFlare for DDoS protection and caching
- **Bucket Policy**: Deny listing, allow only read access
- **Access Logging**: Enable TOS access logs for monitoring
- **Lifecycle Policies**: Auto-delete videos older than N days
- **Rate Limiting**: Implement at application level (not TOS)
- **Hotlink Protection**: Restrict by Referer header (optional)

## Troubleshooting

### Access Denied Error

**Symptoms:** 
```json
{
  "Code":"AccessDenied",
  "Message":"Access Denied",
  "EC":"0003-00000015"
}
```

**Cause:** Objects uploaded with private ACL

**Fix:**
```bash
# Run the ACL fix utility
python fix_tos_acl.py
```

This will:
1. Set bucket ACL to Public Read
2. Set all existing videos to Public Read
3. Verify public access

**Manual Fix (TOS Console):**
1. Go to TOS Console → Buckets
2. Select your bucket
3. Settings → Access Permissions → Edit
4. Change to "Public Read"
5. For each object: Right-click → Permissions → Public Read

### Video Upload Fails

**Check:**
1. TOS credentials configured correctly
2. Network connectivity to TOS endpoint
3. Bucket permissions and quotas
4. Log messages for specific error

**Fix:**
```bash
# Verify credentials
echo $TOS_ACCESS_KEY
echo $TOS_SECRET_KEY

# Test bucket access
python -c "from ai_svc.dictionary.tos_storage import init_bucket; init_bucket('test-bucket')"
```

### Videos Not Persisted

**Symptoms:** Videos expire after 24 hours

**Cause:** TOS upload silently failing

**Fix:**
1. Check logs for warning: "TOS upload failed"
2. Verify TOS credentials are set
3. Test upload manually

### Path Sanitization Issues

**Symptoms:** Videos not found at expected path

**Cause:** Special characters in word/phrase

**Example:**
- Input: `"don't panic"`
- Sanitized: `dont-panic`
- Path: `dont/dont-panic/1710554231.mp4`

## Future Improvements

1. **CDN Integration**: Add CloudFlare or similar CDN for faster video delivery
2. **Lifecycle Policies**: Auto-delete videos older than N days
3. **Compression**: Compress videos before upload to save storage
4. **Thumbnails**: Generate thumbnails during upload
5. **Batch Upload**: Queue multiple videos for batch processing
6. **Retry Logic**: Implement exponential backoff for failed uploads
7. **Monitoring**: Add metrics for upload success rate and latency

## Summary

The TOS storage integration ensures AI-generated videos are permanently stored in the cloud, replacing temporary Volcengine URLs that expire in 24 hours. The system gracefully handles failures by falling back to temporary URLs while logging warnings for investigation.

**Key Benefits:**
- ✅ Permanent storage (no 24-hour expiration)
- ✅ Organized structure (`word/phrase/timestamp`)
- ✅ Graceful fallback on upload failures
- ✅ Automatic database migration
- ✅ Backward compatible
- ✅ Public URL access (no authentication needed)
