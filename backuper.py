#!/usr/bin/env python3
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
import fcntl

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = None

def acquire_lock(lock_file):
    global lock_fd
    try:
        lock_fd = open(lock_file, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except (IOError, OSError):
        logger.warning("Another instance is already running, exiting.")
        return False

def setup_logging(log_file="backup.log"):
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
    with open(config_file, 'r', encoding='utf-8') as f:
        return json.load(f)

def parse_duration(duration_str):
    if not duration_str:
        return 0
    match = re.match(r'^(\d+)([mhdw])$', duration_str.lower().strip())
    if not match:
        logger.error(f"Invalid duration format: '{duration_str}'")
        return 0
    value = int(match.group(1))
    unit = match.group(2)
    multipliers = {'m': 60, 'h': 3600, 'd': 86400, 'w': 604800}
    return value * multipliers.get(unit, 0)

def get_api_url(config):
    return f"https://{config['ptaf_ip']}{config['url_api']}"

def wait_for_ptaf_online(session, config, timeout=3600):
    url = get_api_url(config)
    try:
        session.get(url, verify=False, timeout=5)
        logger.info("PT AF API is available (quick check)")
        return True
    except requests.exceptions.RequestException:
        pass

    logger.info(f"PT AF API did not respond, waiting up to {timeout}s...")
    start = time.time()
    attempt = 0
    while time.time() - start < timeout:
        attempt += 1
        try:
            session.get(url, verify=False, timeout=10)
            logger.info(f"PT AF API became available (attempt {attempt})")
            return True
        except requests.exceptions.RequestException:
            logger.debug("Retrying in 30s...")
        time.sleep(30)
    logger.error("PT AF API did not become available within timeout")
    return False

def authenticate(session, config):
    url = get_api_url(config)
    fingerprint = str(uuid.uuid4())

    logger.info("Step 1: Getting refresh token...")
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
            logger.error(f"Auth failed: {response.status_code} - {response.text}")
            return False
        refresh_token = response.json().get('refresh_token')
        if not refresh_token:
            logger.error("No refresh_token")
            return False
        logger.info("Refresh token obtained")
    except Exception as e:
        logger.error(f"Auth error: {e}")
        return False

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
            logger.error(f"Token error: {response.status_code} - {response.text}")
            return False
        access_token = response.json().get('access_token')
        if not access_token:
            logger.error("No access_token")
            return False
        session.headers.update({
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        })
        logger.info("Access token obtained")
        return True
    except Exception as e:
        logger.error(f"Token error: {e}")
        return False

def create_backup(session, config):
    url = f"{get_api_url(config)}/backups/backups"
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    backup_name = f"auto_backup_{timestamp}"
    backup_data = {"name": backup_name}
    logger.info(f"Creating backup: {backup_name}")
    try:
        response = session.post(url, json=backup_data, verify=False, timeout=30)
        if response.status_code == 201:
            backup_id = response.json().get('id')
            logger.info(f"Backup created, ID: {backup_id}")
            return backup_id
        else:
            logger.error(f"Create failed: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"Create error: {e}")
        return None

def wait_for_backup(session, config, backup_id, max_attempts=60):
    url = f"{get_api_url(config)}/backups/backups/{backup_id}"
    logger.info(f"Waiting for backup {backup_id}...")
    for attempt in range(max_attempts):
        try:
            response = session.get(url, verify=False, timeout=30)
            response.raise_for_status()
            data = response.json()
            last_op = data.get('last_operation', {})
            op_type = last_op.get('type', '').upper()
            op_status = last_op.get('status', '').upper()
            logger.info(f"Attempt {attempt+1}/{max_attempts}: {op_type} - {op_status}")
            if op_status == 'COMPLETED' and op_type == 'CREATING':
                logger.info("Backup completed")
                return True
            elif op_status == 'FAILED':
                logger.error("Backup failed")
                return False
            time.sleep(10)
        except Exception as e:
            logger.error(f"Status check error: {e}")
            return False
    logger.error("Timeout waiting for backup")
    return False

def download_backup(session, config, backup_id):
    url = f"{get_api_url(config)}/backups/backups/{backup_id}/file"
    logger.info("Downloading backup...")
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
    except Exception as e:
        logger.error(f"Download error: {e}")
        return None

def get_all_backups(session, config):
    url = f"{get_api_url(config)}/backups/backups"
    try:
        response = session.get(url, verify=False, timeout=30)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and 'items' in data:
            return data['items']
        elif isinstance(data, list):
            return data
        else:
            logger.warning(f"Unexpected response format: {type(data)}")
            return []
    except Exception as e:
        logger.error(f"Failed to list backups: {e}")
        return []

def delete_backup_api(session, config, backup_id, backup_name):
    url = f"{get_api_url(config)}/backups/backups/{backup_id}"
    try:
        response = session.delete(url, verify=False, timeout=30)
        if response.status_code in (204, 404):
            logger.info(f"Deleted/removed backup: {backup_name}")
            return True
        else:
            logger.error(f"Delete failed: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Delete error: {e}")
        return False

def cleanup_old_backups(session, config):
    ttl_str = config.get('backup_ttl', '30d')
    ttl_seconds = parse_duration(ttl_str)
    if ttl_seconds == 0:
        logger.warning("Invalid TTL, skipping cleanup")
        return

    save_path = config.get('path_to_save_backups', '.')
    current_time = time.time()
    logger.info(f"Cleanup: TTL = {ttl_seconds}s, deleting older than {datetime.fromtimestamp(current_time - ttl_seconds)}")

    # Local files
    if os.path.exists(save_path):
        deleted_local = 0
        for filename in os.listdir(save_path):
            if filename.endswith('.backup'):
                filepath = os.path.join(save_path, filename)
                if current_time - os.path.getmtime(filepath) > ttl_seconds:
                    try:
                        os.remove(filepath)
                        deleted_local += 1
                        logger.info(f"Deleted local: {filename}")
                    except Exception as e:
                        logger.error(f"Failed to delete {filename}: {e}")
        logger.info(f"Local cleanup: deleted {deleted_local} files")
    else:
        logger.warning(f"Backup directory not found: {save_path}")

    # API backups
    backups = get_all_backups(session, config)
    if backups:
        deleted_api = 0
        for backup in backups:
            if not isinstance(backup, dict):
                continue
            backup_id = backup.get('id')
            backup_name = backup.get('name', 'Unknown')
            created_on = backup.get('created_on', 0)
            if not created_on:
                continue
            if current_time - created_on > ttl_seconds:
                if delete_backup_api(session, config, backup_id, backup_name):
                    deleted_api += 1
        logger.info(f"API cleanup: deleted {deleted_api} backups")

def main():
    global logger
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_file = os.path.join(script_dir, 'backup.log')
    logger = setup_logging(log_file)

    logger.info("=" * 60)
    logger.info("PT AF Backup started")

    config_file = os.path.join(script_dir, 'data.json')
    config = load_config(config_file)

    required = ['ptaf_ip', 'ptaf_login', 'ptaf_password', 'path_to_save_backups']
    missing = [f for f in required if not config.get(f)]
    if missing:
        logger.error(f"Missing fields: {', '.join(missing)}")
        sys.exit(1)

    lock_file = os.path.join(script_dir, '.backup.lock')
    if not acquire_lock(lock_file):
        sys.exit(0)

    session = requests.Session()

    if not wait_for_ptaf_online(session, config, config.get('wait_timeout', 3600)):
        logger.error("PT AF unreachable")
        sys.exit(1)

    if not authenticate(session, config):
        logger.error("Authentication failed")
        sys.exit(1)

    cleanup_old_backups(session, config)

    backup_id = create_backup(session, config)
    if not backup_id:
        sys.exit(1)

    if not wait_for_backup(session, config, backup_id):
        sys.exit(1)

    if not download_backup(session, config, backup_id):
        sys.exit(1)

    logger.info("PT AF Backup completed successfully")
    logger.info("=" * 60)

if __name__ == "__main__":
    main()
