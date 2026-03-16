from dotenv import load_dotenv
import os
import logging
from google.cloud import storage
from google.cloud.exceptions import NotFound
from typing import Union

load_dotenv()
logger = logging.getLogger(__name__)

service_account_file = os.getenv("GCP_SERVICE_ACCOUNT_FILE")
client = storage.Client.from_service_account_json(service_account_file)

def get_bucket(bucket_name):
    """
    Retrieve the bucket for phrase usage, or create a new one in GCP Storage if not found.
    """
    try:
        bucket = client.get_bucket(bucket_name)

    # catch not found error, add fallback exception handling if it is not NotFound.
    except NotFound:
        logger.info(f"Bucket {bucket_name} not found. Creating a new bucket.")
        bucket = client.bucket(bucket_name)
        try:
            bucket = client.create_bucket(bucket, location="US")
            logger.info(f"Bucket {bucket_name} created successfully.")

        except Exception as e:
            logger.error(f"Failed to create bucket {bucket_name}: {e}")
            bucket = None
        
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        bucket = None
    
    return bucket

def upload_file_to_bucket(bucket: Union[storage.Bucket, str], file_name_to_save: str, file_path: str) -> bool:
    """
    Upload a file to the specified bucket in GCP Storage.

    Args:
        bucket (Union[storage.Bucket, str]): The bucket object or bucket name where the file will be uploaded.
        file_name_to_save (str): The name to save the file as in the bucket.
        file_path (str): The local path of the file to be uploaded.
    Returns:
        bool: True if the file was uploaded successfully, False otherwise.

        
    """
    try:
        if isinstance(bucket, str):
            bucket = client.get_bucket(bucket)
        blob = bucket.blob(file_name_to_save)
        blob.upload_from_filename(file_path)
        logger.info(f"File {file_name_to_save} uploaded to {file_name_to_save} in bucket {bucket.name}.")
        return True
    except Exception as e:
        logger.error(f"Failed to upload file {file_name_to_save} to bucket {bucket.name}: {e}")
        return False

# bucket_name = f"{os.getenv("BUCKET_NAME_PREFIX")}video_bucket_for_ai_generated_phrase_usage"

# upload_file_to_bucket(bucket_name, "cartoon/pipe down.mp4", os.path.join('/Users/jiali/Downloads/', 'video.mp4'))
