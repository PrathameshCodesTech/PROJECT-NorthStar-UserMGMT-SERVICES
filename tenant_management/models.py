"""
Tenant Database Management Models - Service 2
"""

from django.db import models
from django.utils import timezone
from cryptography.fernet import Fernet
from django.conf import settings
import uuid
import hashlib
import base64
from django.core.validators import RegexValidator



class TenantDatabaseInfo(models.Model):
    """Store tenant database connection details in main database"""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Tenant identification
    tenant_slug = models.CharField(
    max_length=50,
    unique=True,
    help_text="URL-safe tenant identifier like 'techcorp', 'microsoft'",
    validators=[RegexValidator(
        regex=r'^[a-z0-9-]{3,50}$',
        message="tenant_slug must be 3–50 chars: lowercase letters, numbers, hyphens"
    )]
    )

    company_name = models.CharField(
        max_length=200,
        help_text="Full company name like 'TechCorp Inc.'"
    )
    
    # Database connection details
    database_name = models.CharField(
        max_length=100,
        help_text="Physical database name like 'techcorp_compliance_db'"
    )
    database_user = models.CharField(max_length=50)
    database_password = models.TextField(help_text="Encrypted password")
    database_host = models.CharField(max_length=100, default='localhost')
    database_port = models.CharField(max_length=10, default='5432')
    
    # Subscription info
    subscription_plan = models.CharField(
        max_length=20,
        choices=[
            ('BASIC', 'Basic'),
            ('PROFESSIONAL', 'Professional'),
            ('ENTERPRISE', 'Enterprise'),
        ],
        default='BASIC'
    )
    
    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=[
            ('PROVISIONING', 'Provisioning'),
            ('ACTIVE', 'Active'),
            ('SUSPENDED', 'Suspended'),
            ('INACTIVE', 'Inactive'),
            ('PROVISIONING_FAILED', 'Provisioning Failed'),
        ],
        default='ACTIVE'
    )

    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'tenant_database_info'
        ordering = ['tenant_slug']
        
    def __str__(self):
        return f"{self.company_name} ({self.tenant_slug})"
    
    def encrypt_password(self, raw_password):
        """Encrypt database password"""
        key_material = settings.SECRET_KEY.encode()
        key_hash = hashlib.sha256(key_material).digest()
        key = base64.urlsafe_b64encode(key_hash)
        
        f = Fernet(key)
        encrypted = f.encrypt(raw_password.encode())
        self.database_password = encrypted.decode()
    
    def decrypt_password(self):
        """Decrypt database password"""
        key_material = settings.SECRET_KEY.encode()
        key_hash = hashlib.sha256(key_material).digest()
        key = base64.urlsafe_b64encode(key_hash)
        
        f = Fernet(key)
        decrypted = f.decrypt(self.database_password.encode())
        return decrypted.decode()