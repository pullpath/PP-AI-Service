from dotenv import load_dotenv
import os
import logging
import tos
import http
from typing import Any, Optional
import requests
import time
from urllib.parse import urlparse
from pathlib import Path


# 您需要安装 python-devel 包。
# TOS Python SDK 依赖 crcmod 计算 CRC 校验码，而 crcmod 的 C 扩展模式依赖 python-devel 包中的 Python.h 文件。如果缺少 Python.h，crcmod 的 C 扩展模式安装失败，crcmod 会运行在纯 Python 模式，纯 Python 模式计算 CRC 性能远差于 C 扩展模式 ，会导致上传、下载等操作效率低下。
# 如果您是 Debian、Ubuntu 系统，您可以使用以下命令安装：

# 进入 Python 环境，输入 import crcmod._crcfunext, 如果出现以下错误提示，则表明 crcmod 库的 C 扩展模式安装失败，crcmod 库是纯 Python 方式。原因是编译 crcmod 时，_crcfunext.so 依赖 Python.h 文件，而系统中缺少这个头文件，因此 _crcfunext.so 库生成失败。
# Traceback (most recent call last):
#File "<stdin>", line 1, in <module>
# ImportError: No module named _crcfunext

# Python2.x版本
# apt-get install python-dev

# Python3.x版本
# apt-get install python3-dev

load_dotenv()
logger = logging.getLogger(__name__)

access_key = os.getenv("TOS_ACCESS_KEY")
secret_key = os.getenv("TOS_SECRET_KEY")
endpoint = "tos-cn-beijing.volces.com"
region = "cn-beijing"

def init_bucket(bucket_name: str):
    """
    Creates a new bucket in the TOS (Tencent Object Storage) service.

    Args:
        bucket_name (str): The name of the bucket to create.

    Raises:
        tos.exceptions.TosClientError: If a client-side error occurs, such as invalid request parameters or network issues.
        tos.exceptions.TosServerError: If a server-side error occurs, detailed error information can be obtained from the exception.
        Exception: For any other unknown errors.

    Note:
        Logs detailed error information for troubleshooting, including request ID, error code, HTTP status code, and request URL.
    """
    if not access_key or not secret_key:
        logger.error("TOS credentials not configured")
        return False
    
    try:
        client = tos.TosClientV2(access_key, secret_key, endpoint, region)
        try:
            client.head_bucket(bucket_name)
            logger.info(f"Bucket '{bucket_name}' already exists.")
            client.close()
            return True
        except tos.exceptions.TosServerError as e:
            if e.status_code != http.HTTPStatus.NOT_FOUND:
                client.close()
                raise Exception("Unexpected error when checking bucket existence: {}".format(e))
        
        client.create_bucket(bucket_name, acl=tos.ACLType.ACL_Public_Read)
        logger.info(f"Bucket '{bucket_name}' created with ACL_Public_Read for public video access")
        client.close()
        return True
    except tos.exceptions.TosClientError as e:
        logger.error('fail with client error, message:{}, cause: {}'.format(e.message, e.cause))
        return False
    except tos.exceptions.TosServerError as e:
        logger.error('fail with server error, code: {}'.format(e.code))
        logger.error('error with request id: {}'.format(e.request_id))
        logger.error('error with message: {}'.format(e.message))
        logger.error('error with http code: {}'.format(e.status_code))
        logger.error('error with ec: {}'.format(e.ec))
        logger.error('error with request url: {}'.format(e.request_url))
        return False
    except Exception as e:
        logger.error('fail with unknown error: {}'.format(e))
        return False
    
def put_object(bucket_name: str, object_key: str, data: Any, acl: tos.ACLType = tos.ACLType.ACL_Public_Read):
    """
    Uploads an object to a specified bucket in the TOS (Tencent Object Storage) service.

    Args:
        bucket_name (str): The name of the bucket to which the object will be uploaded.
        object_key (str): The key (name) of the object to be uploaded.
        data (bytes): The binary data of the object to be uploaded.
        acl: ACL type for the object (default: ACL_Public_Read for public access)
    Raises:
        tos.exceptions.TosClientError: If a client-side error occurs, such as invalid request parameters or network issues.
        tos.exceptions.TosServerError: If a server-side error occurs, detailed error information can be obtained from the exception.
        Exception: For any other unknown errors.
    Note:
        Logs detailed error information for troubleshooting, including request ID, error code, HTTP status code, and request URL.
    """
    if not access_key or not secret_key:
        logger.error("TOS credentials not configured")
        return False
    
    try:
        client = tos.TosClientV2(access_key, secret_key, endpoint, region)
        client.put_object(bucket_name, object_key, content=data, acl=acl)
        logger.info(f"Object '{object_key}' uploaded successfully to bucket '{bucket_name}' with ACL: {acl.value}.")
        client.close()
        return True
    except tos.exceptions.TosClientError as e:
        logger.error('fail with client error, message:{}, cause: {}'.format(e.message, e.cause))
        return False
    except tos.exceptions.TosServerError as e:
        logger.error('fail with server error, code: {}'.format(e.code))
        logger.error('error with request id: {}'.format(e.request_id))
        logger.error('error with message: {}'.format(e.message))
        logger.error('error with http code: {}'.format(e.status_code))
        logger.error('error with ec: {}'.format(e.ec))
        logger.error('error with request url: {}'.format(e.request_url))
        return False

    except Exception as e:
        logger.error('fail with unknown error: {}'.format(e))
        return False
        

def _infer_file_extension(url: str) -> str:
    """
    Infer file extension from URL
    
    Args:
        url: The video URL
        
    Returns:
        File extension with dot (e.g., '.mp4')
    """
    parsed_url = urlparse(url)
    path = parsed_url.path
    
    # Extract extension from path
    ext = Path(path).suffix
    
    # Default to .mp4 if no extension found
    if not ext:
        ext = '.mp4'
        
    return ext


def _sanitize_path_component(component: str) -> str:
    """
    Sanitize a path component to be filesystem-safe
    
    Args:
        component: Path component to sanitize
        
    Returns:
        Sanitized path component
    """
    # Replace spaces and special characters with hyphens
    sanitized = component.strip().lower()
    # Keep alphanumeric, hyphens, and underscores
    sanitized = ''.join(c if c.isalnum() or c in '-_' else '-' for c in sanitized)
    # Remove consecutive hyphens
    while '--' in sanitized:
        sanitized = sanitized.replace('--', '-')
    # Remove leading/trailing hyphens
    sanitized = sanitized.strip('-')
    
    return sanitized


def download_and_upload_video(
    video_url: str,
    word: str,
    phrase: str,
    bucket_name: str,
    style: str
) -> Optional[str]:
    """
    Download video from Volcengine URL and upload to TOS storage
    
    Args:
        video_url: Source video URL from Volcengine
        word: The dictionary word
        phrase: The phrase being illustrated
        bucket_name: Bucket name for TOS storage (required)
        style: Video style (e.g., 'kids_cartoon', 'realistic')
        
    Returns:
        TOS public URL if successful, None if failed
        
    Structure: [word]/[phrase]/[style]/[timestamp].[suffix]
    Example: hello/pipe-down/kids-cartoon/1710554231.mp4
    """
    if not access_key or not secret_key:
        logger.error("TOS credentials not configured - cannot upload video")
        return None
    
    # Ensure bucket exists
    if not init_bucket(bucket_name):
        logger.error(f"Failed to initialize bucket '{bucket_name}'")
        return None
    
    try:
        # Download video from Volcengine URL
        logger.info(f"Downloading video from {video_url}")
        response = requests.get(video_url, timeout=60, stream=True)
        response.raise_for_status()
        
        video_content = response.content
        logger.info(f"Downloaded {len(video_content)} bytes from Volcengine")
        
        # Build object key: [word]/[phrase]/[style]/[timestamp].[suffix]
        sanitized_word = _sanitize_path_component(word)
        sanitized_phrase = _sanitize_path_component(phrase)
        sanitized_style = _sanitize_path_component(style)
        timestamp = int(time.time())
        extension = _infer_file_extension(video_url)
        
        object_key = f"{sanitized_word}/{sanitized_phrase}/{sanitized_style}/{timestamp}{extension}"
        
        logger.info(f"Uploading video to TOS: {object_key}")
        
        # Upload to TOS
        if not put_object(bucket_name, object_key, video_content):
            logger.error(f"Failed to upload video to TOS: {object_key}")
            return None
        
        # Construct public URL
        # Format: https://{bucket_name}.{endpoint}/{object_key}
        tos_url = f"https://{bucket_name}.{endpoint}/{object_key}"
        
        logger.info(f"Video uploaded successfully to TOS: {tos_url}")
        return tos_url
        
    except requests.RequestException as e:
        logger.error(f"Error downloading video from {video_url}: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during video upload: {str(e)}")
        return None