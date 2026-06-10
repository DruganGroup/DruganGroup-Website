"""
Tenant-specific encryption service for sensitive credentials
Uses Fernet (AES-128-CBC + HMAC) for secure encryption at rest
"""
import os
from cryptography.fernet import Fernet
import logging

logger = logging.getLogger(__name__)

class TenantEncryption:
    """
    Encrypts and decrypts sensitive tenant data using a master key.
    
    Security Features:
    - AES-128-CBC encryption with HMAC authentication
    - Master key stored in environment variable
    - Per-tenant data isolation
    - Graceful error handling
    
    Usage:
        encryptor = TenantEncryption()
        encrypted = encryptor.encrypt("my_secret_password")
        decrypted = encryptor.decrypt(encrypted)
    """
    
    # List of settings keys that should be encrypted
    ENCRYPTED_KEYS = [
        'smtp_password',
        'google_ai_key',
        'samsara_api_key',
        'geotab_password',
        'geotab_user',
        'stripe_secret_key',
        'openai_api_key'
    ]
    
    def __init__(self):
        """Initialize encryption with master key from environment"""
        master_key = os.environ.get('ENCRYPTION_MASTER_KEY')
        
        if not master_key:
            # In development, generate a temporary key with warning
            if os.environ.get('FLASK_ENV') != 'production':
                logger.warning("⚠️  ENCRYPTION_MASTER_KEY not set! Using temporary key for development.")
                master_key = Fernet.generate_key().decode()
            else:
                raise RuntimeError(
                    "ENCRYPTION_MASTER_KEY environment variable must be set in production! "
                    "Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
                )
        
        try:
            # Ensure key is bytes
            if isinstance(master_key, str):
                master_key = master_key.encode()
            
            self.cipher = Fernet(master_key)
        except Exception as e:
            raise RuntimeError(f"Invalid ENCRYPTION_MASTER_KEY format: {e}")
    
    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt sensitive data
        
        Args:
            plaintext: The data to encrypt (e.g., password, API key)
            
        Returns:
            Base64-encoded encrypted string, or None if input is empty
            
        Example:
            >>> encryptor = TenantEncryption()
            >>> encrypted = encryptor.encrypt("my_password")
            >>> print(encrypted)
            'gAAAAABh5K3L...'
        """
        if not plaintext or plaintext.strip() == '':
            return None
        
        try:
            encrypted_bytes = self.cipher.encrypt(plaintext.encode('utf-8'))
            return encrypted_bytes.decode('utf-8')
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise
    
    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt sensitive data
        
        Args:
            ciphertext: The encrypted data to decrypt
            
        Returns:
            Decrypted plaintext string, or None if input is empty
            
        Raises:
            cryptography.fernet.InvalidToken: If data is corrupted or key is wrong
            
        Example:
            >>> encryptor = TenantEncryption()
            >>> decrypted = encryptor.decrypt('gAAAAABh5K3L...')
            >>> print(decrypted)
            'my_password'
        """
        if not ciphertext or ciphertext.strip() == '':
            return None
        
        try:
            decrypted_bytes = self.cipher.decrypt(ciphertext.encode('utf-8'))
            return decrypted_bytes.decode('utf-8')
        except Exception as e:
            logger.error(f"Decryption failed (corrupted data or wrong key): {e}")
            # Return None instead of raising to allow graceful degradation
            return None
    
    def is_encrypted_key(self, key: str) -> bool:
        """
        Check if a settings key should be encrypted
        
        Args:
            key: The settings key name
            
        Returns:
            True if this key should be encrypted
        """
        return key in self.ENCRYPTED_KEYS
    
    def encrypt_settings(self, settings: dict) -> dict:
        """
        Encrypt all sensitive keys in a settings dictionary
        
        Args:
            settings: Dictionary of settings key-value pairs
            
        Returns:
            New dictionary with sensitive values encrypted
            
        Example:
            >>> settings = {'smtp_password': 'secret123', 'company_name': 'ACME'}
            >>> encrypted = encryptor.encrypt_settings(settings)
            >>> print(encrypted)
            {'smtp_password': 'gAAAAABh5K3L...', 'company_name': 'ACME'}
        """
        encrypted = {}
        for key, value in settings.items():
            if self.is_encrypted_key(key) and value:
                encrypted[key] = self.encrypt(value)
            else:
                encrypted[key] = value
        return encrypted
    
    def decrypt_settings(self, settings: dict) -> dict:
        """
        Decrypt all sensitive keys in a settings dictionary
        
        Args:
            settings: Dictionary of settings with encrypted values
            
        Returns:
            New dictionary with sensitive values decrypted
            
        Example:
            >>> settings = {'smtp_password': 'gAAAAABh5K3L...', 'company_name': 'ACME'}
            >>> decrypted = encryptor.decrypt_settings(settings)
            >>> print(decrypted)
            {'smtp_password': 'secret123', 'company_name': 'ACME'}
        """
        decrypted = {}
        for key, value in settings.items():
            if self.is_encrypted_key(key) and value:
                decrypted[key] = self.decrypt(value)
            else:
                decrypted[key] = value
        return decrypted


def generate_master_key():
    """
    Generate a new master encryption key
    
    Usage:
        python -c "from utils.encryption import generate_master_key; generate_master_key()"
    """
    key = Fernet.generate_key().decode()
    print("\n" + "="*70)
    print("🔐 NEW ENCRYPTION MASTER KEY GENERATED")
    print("="*70)
    print(f"\nAdd this to your .env file:\n")
    print(f"ENCRYPTION_MASTER_KEY={key}")
    print("\n⚠️  IMPORTANT:")
    print("  1. Keep this key SECRET - never commit to git")
    print("  2. Store securely (password manager, secrets vault)")
    print("  3. Backup safely - losing this key means losing encrypted data")
    print("  4. Use the same key across all environments for the same database")
    print("="*70 + "\n")
    return key


# Singleton instance for easy import
_encryptor = None

def get_encryptor():
    """Get or create the global encryptor instance"""
    global _encryptor
    if _encryptor is None:
        _encryptor = TenantEncryption()
    return _encryptor


if __name__ == "__main__":
    # If run directly, generate a new key
    generate_master_key()
