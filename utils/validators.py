"""
Security validation utilities for DruganGroup Website
"""
import re
from typing import Tuple

# Whitelist of allowed database table names
ALLOWED_TABLES = [
    'companies', 'users', 'invoices', 'vehicles', 'jobs', 'clients',
    'properties', 'quotes', 'materials', 'staff', 'maintenance_logs',
    'settings', 'transactions', 'payroll', 'overheads', 'certificates',
    'rams_documents', 'job_diary', 'job_materials', 'job_photos',
    'service_requests', 'audit_logs', 'system_logs', 'plans'
]

import os
from werkzeug.utils import secure_filename
from flask import current_app

def delete_file_safely(db_path: str):
    """
    Safely deletes a file from the disk based on its database path.
    """
    if not db_path: return
    
    # Clean the path to prevent directory traversal
    clean_path = db_path.lstrip('/')
    if clean_path.startswith('uploads/'):
        abs_path = os.path.join(current_app.static_folder, clean_path)
        if os.path.exists(abs_path):
            try:
                os.remove(abs_path)
            except Exception as e:
                import logging
                logging.error(f"Error deleting file {abs_path}: {e}")

def save_secure_file(file, relative_dir, prefix=""):
    """
    Validates and securely saves an uploaded file.
    
    Args:
        file: The file object from request.files
        relative_dir: Directory relative to static/uploads/ (e.g. 'company_1/job_evidence')
        prefix: Optional prefix for filename (e.g. 'JOB_123_')
        
    Returns:
        str: Database path (e.g. '/uploads/company_1/job_evidence/file.pdf') or None if invalid
    """
    if not file or not file.filename:
        return None
        
    # Strict extension checking
    ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'csv', 'xls', 'xlsx', 'doc', 'docx'}
    if '.' not in file.filename or file.filename.rsplit('.', 1)[1].lower() not in ALLOWED_EXTENSIONS:
        raise ValueError("File type not allowed. Only PDF, images, and Office documents are permitted.")

    # Secure filename
    import time
    safe_name = secure_filename(file.filename)
    final_name = f"{prefix}{int(time.time())}_{safe_name}"
    
    # Ensure directory exists
    save_dir = os.path.join(current_app.static_folder, 'uploads', relative_dir)
    os.makedirs(save_dir, exist_ok=True)
    
    # Save file
    file.save(os.path.join(save_dir, final_name))
    
    # Return path formatted for DB
    return f"/uploads/{relative_dir}/{final_name}"

def validate_table_name(table: str) -> str:
    """
    Validate that a table name is in the allowed whitelist.
    Prevents SQL injection via dynamic table names.
    
    Args:
        table: The table name to validate
        
    Returns:
        The validated table name
        
    Raises:
        ValueError: If table name is not in whitelist
    """
    if table not in ALLOWED_TABLES:
        raise ValueError(f"Invalid table name: {table}")
    return table

def validate_password(password: str) -> Tuple[bool, str]:
    """
    Validate password complexity requirements.
    
    Args:
        password: The password to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter"
    
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter"
    
    if not re.search(r"\d", password):
        return False, "Password must contain at least one number"
    
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return False, "Password must contain at least one special character"
    
    return True, "Valid"

def validate_email(email: str) -> bool:
    """
    Validate email format.
    
    Args:
        email: The email address to validate
        
    Returns:
        True if valid, False otherwise
    """
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))

def validate_phone(phone: str) -> bool:
    """
    Validate UK phone number format.
    
    Args:
        phone: The phone number to validate
        
    Returns:
        True if valid, False otherwise
    """
    # Remove spaces and common separators
    cleaned = re.sub(r'[\s\-\(\)]', '', phone)
    
    # UK phone patterns
    patterns = [
        r'^(\+44|0044|0)[1-9]\d{9}$',  # Standard UK format
        r'^(\+44|0044|0)7\d{9}$',       # Mobile
    ]
    
    return any(re.match(pattern, cleaned) for pattern in patterns)

def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename to prevent directory traversal attacks.
    
    Args:
        filename: The filename to sanitize
        
    Returns:
        Sanitized filename
    """
    # Remove any path components
    filename = filename.split('/')[-1].split('\\')[-1]
    
    # Remove any non-alphanumeric characters except dots, dashes, and underscores
    filename = re.sub(r'[^a-zA-Z0-9._-]', '', filename)
    
    # Limit length
    if len(filename) > 255:
        name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
        filename = name[:250] + ('.' + ext if ext else '')
    
    return filename

def validate_subdomain(subdomain: str) -> bool:
    """
    Validate subdomain format.
    
    Args:
        subdomain: The subdomain to validate
        
    Returns:
        True if valid, False otherwise
    """
    # Subdomain must be lowercase alphanumeric with hyphens
    # Must start and end with alphanumeric
    pattern = r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$'
    return bool(re.match(pattern, subdomain))

def extract_subdomain(host: str, base_domain: str) -> str:
    """
    Safely extract subdomain from hostname.
    
    Args:
        host: The full hostname
        base_domain: The base domain (e.g., 'businessbetter.co.uk')
        
    Returns:
        The subdomain or None if invalid
    """
    # Validate hostname format
    pattern = r'^[a-z0-9-]+\.' + re.escape(base_domain) + '$'
    if not re.match(pattern, host.lower()):
        return None
    
    subdomain = host.lower().replace(f'.{base_domain}', '').split('.')[0]
    
    # Validate the extracted subdomain
    if validate_subdomain(subdomain):
        return subdomain
    
    return None
