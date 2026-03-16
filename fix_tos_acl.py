#!/usr/bin/env python3
"""
Utility script to fix ACL permissions for existing TOS bucket and videos

This script:
1. Sets bucket ACL to Public Read
2. Sets all existing video objects to Public Read
3. Verifies public access

Run: python fix_tos_acl.py
"""

import os
import tos
from dotenv import load_dotenv

load_dotenv()

access_key = os.getenv("TOS_ACCESS_KEY")
secret_key = os.getenv("TOS_SECRET_KEY")
endpoint = "tos-cn-beijing.volces.com"
region = "cn-beijing"
bucket_name_prefix = os.getenv("BUCKET_NAME_PREFIX", "")
bucket_name = f"{bucket_name_prefix}video-bucket-for-ai-generated-phrase-usage"

def fix_bucket_acl():
    """Set bucket ACL to Public Read"""
    print(f"Fixing ACL for bucket: {bucket_name}")
    
    if not access_key or not secret_key:
        print("ERROR: TOS credentials not configured")
        return False
    
    try:
        client = tos.TosClientV2(access_key, secret_key, endpoint, region)
        
        # Set bucket ACL to Public Read
        client.put_bucket_acl(bucket_name, acl=tos.ACLType.ACL_Public_Read)
        print(f"✓ Bucket ACL set to Public Read")
        
        client.close()
        return True
    except Exception as e:
        print(f"✗ Failed to set bucket ACL: {e}")
        return False


def fix_objects_acl():
    """Set ACL for all objects in bucket to Public Read"""
    print(f"\nFixing ACL for all objects in bucket: {bucket_name}")
    
    if not access_key or not secret_key:
        print("ERROR: TOS credentials not configured")
        return False
    
    try:
        client = tos.TosClientV2(access_key, secret_key, endpoint, region)
        
        # List all objects
        is_truncated = True
        continuation_token = ""
        total_objects = 0
        fixed_objects = 0
        
        while is_truncated:
            if continuation_token:
                result = client.list_objects_type2(
                    bucket_name, 
                    continuation_token=continuation_token
                )
            else:
                result = client.list_objects_type2(bucket_name)
            
            # Process objects
            for obj in result.contents:
                key = obj.key
                try:
                    client.put_object_acl(bucket_name, key, acl=tos.ACLType.ACL_Public_Read)
                    fixed_objects += 1
                    print(f"✓ Fixed ACL for: {key}")
                except Exception as e:
                    print(f"✗ Failed to fix ACL for {key}: {e}")
                
                total_objects += 1
            
            is_truncated = result.is_truncated
            if is_truncated:
                continuation_token = result.next_continuation_token
        
        print(f"\n✓ Fixed ACL for {fixed_objects}/{total_objects} objects")
        
        client.close()
        return True
    except Exception as e:
        print(f"✗ Failed to list/fix objects: {e}")
        return False


def verify_public_access():
    """Verify that objects are publicly accessible"""
    print(f"\nVerifying public access...")
    
    if not access_key or not secret_key:
        print("ERROR: TOS credentials not configured")
        return False
    
    try:
        import requests
        
        client = tos.TosClientV2(access_key, secret_key, endpoint, region)
        
        # Get first object to test
        result = client.list_objects_type2(bucket_name, max_keys=1)
        
        if not result.contents:
            print("No objects found in bucket")
            return True
        
        test_key = result.contents[0].key
        test_url = f"https://{bucket_name}.{endpoint}/{test_key}"
        
        print(f"Testing public access to: {test_url}")
        
        # Try to access without authentication
        response = requests.head(test_url, timeout=10)
        
        if response.status_code == 200:
            print(f"✓ Public access verified! Status: {response.status_code}")
            print(f"✓ Video URL format: https://{bucket_name}.{endpoint}/[word]/[phrase]/[timestamp].mp4")
            return True
        else:
            print(f"✗ Public access failed! Status: {response.status_code}")
            return False
        
    except Exception as e:
        print(f"✗ Failed to verify public access: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("TOS ACL Fix Utility")
    print("=" * 60)
    
    print(f"\nConfiguration:")
    print(f"  Bucket: {bucket_name}")
    print(f"  Endpoint: {endpoint}")
    print(f"  Region: {region}")
    
    # Step 1: Fix bucket ACL
    if not fix_bucket_acl():
        print("\n⚠️  Bucket ACL fix failed. Continuing anyway...")
    
    # Step 2: Fix objects ACL
    if not fix_objects_acl():
        print("\n⚠️  Object ACL fix failed.")
    
    # Step 3: Verify public access
    verify_public_access()
    
    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)
    print("\nAll new videos will be uploaded with Public Read ACL automatically.")
    print("Test a video URL in your browser to verify access.")
