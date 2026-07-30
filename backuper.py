#!/usr/bin/env python3
"""
PT AF Backup Script
"""

import json
import os
import sys
import time
import logging
import re
import uuid
from datetime import datetime
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def setup_logging(log_file="backup.log"):
    """Setup logging"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)


def load_config(config_file="data.json"):
    """Load config from JSON"""
    with open(config_file, 'r', encoding='utf-8') as f:
        config = json.load(f)
    return config


def parse_duration(duration_str):
    """Parse duration string to seconds (30m, 12h, 1d, 2w)"""
    if not duration_str:
        return 0
    
    match = re.match(r'^(\d+)([mhdw])$', duration_str.lower().strip())
    if not match:
        logger.error(f"Invalid duration format: '{duration_str}'")
        return 0
    
    value = int(match.group(1))
    unit = match.group(2)
    
    multipliers = {
        'm': 60,
        'h': 3600,
        'd': 86400,
        'w': 604800
    }
    
    seconds = value * multipliers.get(unit, 0)
    logger.info(f"Parsed duration '{duration_str}' = {seconds} seconds ({seconds/86400:.1f} days)")
    return seconds


def get_api_url(config):
    """Build API URL"""
    return f"https://{config['ptaf_ip']}{config['url_api']}"


def authenticate(session, config):
    """Authenticate to PT AF API"""
    url = get_api_url(config)
    
    # Generate unique fingerprint
    fingerprint = str(uuid.uuid4())
    
    logger.info("Step 1: Getting refresh token...")
    
    #Get refresh token
    auth_url = f"{url}/auth/refresh_tokens"
    auth_data = {
        "username": config['ptaf_login'],
        "password": config['ptaf_password'],
        "fingerprint": fingerprint,
        "ldap": False
    }
    
    try:
        response = session.post(auth_url, json=auth_data, verify=False, timeout=30)
        
        if response.status_code != 201:
            logger.error(f"Authentication failed: POST {auth_url}")
            logger.error(f"Status: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return False
        
        tokens = response.json()
        refresh_token = tokens.get('refresh_token')
        
        if not refresh_token:
            logger.error("No refresh_token in response")
            return False
        
        logger.info("Refresh token obtained")
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Authentication failed: POST {auth_url}")
        logger.error(f"Details: {str(e)}")
        return False
    
    # Get access token
    logger.info("Step 2: Getting access token...")
    
    token_url = f"{url}/auth/access_tokens"
    token_data = {
        "refresh_token": refresh_token,
        "fingerprint": fingerprint,
        "tenant_id": "00000000-0000-0000-0000-000000000000"
    }
    
    try:
        response = session.post(token_url, json=token_data, verify=False, timeout=30)
        
        if response.status_code != 201:
            logger.error(f"Token authorization failed: POST {token_url}")
            logger.error(f"Status: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return False
        
        tokens = response.json()
        access_token = tokens.get('access_token')
        
        if not access_token:
            logger.error("No access_token in response")
            return False
        
        # Set authorization header
        session.headers.update({
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        })
        
        logger.info("Access token obtained, authentication successful")
        return True
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Token authorization failed: POST {token_url}")
        logger.error(f"Details: {str(e)}")
        return False


def create_backup(session, config):
    """Create backup via API"""
    url = f"{get_api_url(config)}/backups/backups"
    
    # Generate backup name with timestamp
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    backup_name = f"auto_backup_{timestamp}"
    
    backup_data = {
        "name": backup_name
    }
    
    logger.info(f"Creating backup: POST {url}")
    logger.info(f"Backup name: {backup_name}")
    
    try:
        response = session.post(url, json=backup_data, verify=False, timeout=30)
        
        if response.status_code == 201:
            backup_info = response.json()
            backup_id = backup_info.get('id')
            logger.info(f"Backup created, ID: {backup_id}")
            return backup_id
        else:
            logger.error(f"Backup creation failed: POST {url}")
            logger.error(f"Status: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return None
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Backup creation failed: POST {url}")
        logger.error(f"Status: {e.response.status_code if hasattr(e, 'response') else 'N/A'}")
        logger.error(f"Details: {str(e)}")
        return None


def wait_for_backup(session, config, backup_id, max_attempts=60):
    """Wait for backup completion"""
    url = f"{get_api_url(config)}/backups/backups/{backup_id}"
    
    logger.info(f"Waiting for backup {backup_id} to complete...")
    
    for attempt in range(max_attempts):
        try:
            response = session.get(url, verify=False, timeout=30)
            response.raise_for_status()
            
            backup = response.json()
            
            if isinstance(backup, dict):
                last_operation = backup.get('last_operation', {})
                op_type = last_operation.get('type', '').upper()
                op_status = last_operation.get('status', '').upper()
                
                logger.info(f"Backup {backup_id}: {op_type} - {op_status} (attempt {attempt + 1}/{max_attempts})")
                
                if op_status == 'COMPLETED' and op_type == 'CREATING':
                    logger.info(f"Backup {backup_id} completed successfully")
                    return True
                elif op_status == 'FAILED':
                    logger.error(f"Backup {backup_id} failed")
                    return False
            else:
                logger.error(f"Unexpected response format: {type(backup)}")
                return False
            
            time.sleep(10)
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Status check failed: GET {url}")
            logger.error(f"Details: {str(e)}")
            return False
    
    logger.error(f"Timeout waiting for backup {backup_id}")
    return False


def download_backup(session, config, backup_id):
    """Download backup file"""
    url = f"{get_api_url(config)}/backups/backups/{backup_id}/file"
    
    logger.info(f"Downloading backup: GET {url}")
    
    try:
        response = session.get(url, verify=False, timeout=300, stream=True)
        response.raise_for_status()
        
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        filename = f"auto_backup_{timestamp}"
        
        save_path = config.get('path_to_save_backups', '.')
        os.makedirs(save_path, exist_ok=True)
        
        filepath = os.path.join(save_path, filename)
        
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        file_size = os.path.getsize(filepath)
        logger.info(f"Backup saved: {filepath} ({file_size} bytes)")
        
        return filepath
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Download failed: GET {url}")
        logger.error(f"Details: {str(e)}")
        return None


def get_all_backups(session, config):
    """Get list of all backups from API"""
    url = f"{get_api_url(config)}/backups/backups"
    
    logger.info(f"Fetching backups list: GET {url}")
    
    try:
        response = session.get(url, verify=False, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        # API returns {"items": [...]}
        if isinstance(data, dict) and 'items' in data:
            backups = data['items']
            logger.info(f"Found {len(backups)} backups in API")
            for backup in backups:
                if isinstance(backup, dict):
                    created_on = backup.get('created_on', 0)
                    created_date = datetime.fromtimestamp(created_on).strftime('%Y-%m-%d %H:%M:%S') if created_on else 'N/A'
                    logger.info(f"  - {backup.get('name')} (ID: {backup.get('id')}, Created: {created_date})")
            return backups
        elif isinstance(data, list):
            # Fallback if API returns array directly
            logger.info(f"Found {len(data)} backups in API (array format)")
            return data
        else:
            logger.warning(f"Unexpected response format: {type(data)}")
            logger.info(f"Response: {data}")
            return []
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to get backups list: GET {url}")
        logger.error(f"Details: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response status: {e.response.status_code}")
            logger.error(f"Response body: {e.response.text}")
        return []


def delete_backup_api(session, config, backup_id, backup_name):
    """Delete backup via API"""
    url = f"{get_api_url(config)}/backups/backups/{backup_id}"
    
    logger.info(f"Deleting backup: DELETE {url}")
    logger.info(f"Backup name: {backup_name}")
    
    try:
        response = session.delete(url, verify=False, timeout=30)
        
        logger.info(f"Delete response status: {response.status_code}")
        
        if response.status_code == 204:
            logger.info(f"Successfully deleted backup from API: {backup_name} (ID: {backup_id})")
            return True
        elif response.status_code == 404:
            logger.warning(f"Backup not found in API (already deleted?): {backup_name}")
            return True
        else:
            logger.error(f"Failed to delete backup from API: {backup_name}")
            logger.error(f"Status: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return False
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to delete backup from API: {backup_name}")
        logger.error(f"Details: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response status: {e.response.status_code}")
            logger.error(f"Response body: {e.response.text}")
        return False


def cleanup_old_backups(session, config):
    """Remove old backups from disk and API (only those older than TTL)"""
    ttl_str = config.get('backup_ttl', '30d')
    ttl_seconds = parse_duration(ttl_str)
    
    if ttl_seconds == 0:
        logger.warning(f"Invalid TTL: {ttl_str}, skipping cleanup")
        return
    
    save_path = config.get('path_to_save_backups', '.')
    current_time = time.time()
    
    logger.info(f"Starting cleanup (TTL: {ttl_str} = {ttl_seconds} seconds = {ttl_seconds/86400:.1f} days)")
    logger.info(f"Current time: {datetime.fromtimestamp(current_time).strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Deleting backups older than: {datetime.fromtimestamp(current_time - ttl_seconds).strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Cleanup local files older than TTL
    if os.path.exists(save_path):
        deleted_local = 0
        
        for filename in os.listdir(save_path):
            if filename.endswith('.backup'):
                filepath = os.path.join(save_path, filename)
                file_age = current_time - os.path.getmtime(filepath)
                
                if file_age > ttl_seconds:
                    try:
                        os.remove(filepath)
                        logger.info(f"Deleted local backup: {filename} (age: {file_age/86400:.1f} days)")
                        deleted_local += 1
                    except OSError as e:
                        logger.error(f"Failed to delete local backup {filename}: {e}")
        
        logger.info(f"Local cleanup complete. Deleted: {deleted_local} files")
    else:
        logger.warning(f"Local backup directory does not exist: {save_path}")
    
    # Cleanup backups in API older than TTL
    logger.info("Fetching backups list from API for cleanup...")
    backups = get_all_backups(session, config)
    
    if backups:
        deleted_api = 0
        skipped_api = 0
        failed_api = 0
        
        for backup in backups:
            if isinstance(backup, dict):
                backup_id = backup.get('id')
                backup_name = backup.get('name', 'Unknown')
                created_on = backup.get('created_on', 0)
                
                # Skip if no valid created_on timestamp
                if not created_on:
                    logger.warning(f"Backup '{backup_name}' has no created_on timestamp, skipping")
                    skipped_api += 1
                    continue
                
                # Calculate backup age
                backup_age = current_time - created_on
                age_days = backup_age / 86400
                
                logger.info(f"Checking backup: '{backup_name}' (age: {age_days:.3f} days, TTL: {ttl_seconds/86400:.3f} days)")
                
                if backup_age > ttl_seconds:
                    logger.info(f"Backup '{backup_name}' is older than TTL ({age_days:.3f} > {ttl_seconds/86400:.3f}) - deleting...")
                    if delete_backup_api(session, config, backup_id, backup_name):
                        deleted_api += 1
                    else:
                        failed_api += 1
                else:
                    logger.info(f"Backup '{backup_name}' is within TTL ({age_days:.3f} <= {ttl_seconds/86400:.3f}) - keeping")
                    skipped_api += 1
        
        logger.info(f"API cleanup complete. Deleted: {deleted_api}, Kept: {skipped_api}, Failed: {failed_api}")
    else:
        logger.warning("No backups found in API or failed to fetch list")


def main():
    """Main function"""
    global logger
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_file = os.path.join(script_dir, 'backup.log')
    logger = setup_logging(log_file)
    
    logger.info("=" * 60)
    logger.info("PT AF Backup started")
    
    config_file = os.path.join(script_dir, 'data.json')
    config = load_config(config_file)
    
    # Check required fields
    required_fields = ['ptaf_ip', 'ptaf_login', 'ptaf_password', 'path_to_save_backups']
    missing_fields = [field for field in required_fields if not config.get(field)]
    
    if missing_fields:
        logger.error(f"Missing required fields: {', '.join(missing_fields)}")
        sys.exit(1)
    
    
    session = requests.Session()
    if not authenticate(session, config):
        logger.error("Authentication failed")
        sys.exit(1)
    
    # Cleanup old backups before creating new one
    cleanup_old_backups(session, config)
    
    # Create backup
    backup_id = create_backup(session, config)
    if not backup_id:
        logger.error("Backup creation failed")
        sys.exit(1)
    
    # Wait for backup
    if not wait_for_backup(session, config, backup_id):
        logger.error("Backup not completed")
        sys.exit(1)
    
    # Download backup
    backup_file = download_backup(session, config, backup_id)
    if not backup_file:
        logger.error("Backup download failed")
        sys.exit(1)
    
    logger.info("PT AF Backup completed successfully")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
