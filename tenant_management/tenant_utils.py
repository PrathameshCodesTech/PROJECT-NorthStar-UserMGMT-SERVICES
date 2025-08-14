"""
Enhanced Tenant Database Management Utilities - Service 2
"""

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from django.conf import settings
from django.core.management import call_command
from django.db import connections
from .models import TenantDatabaseInfo
import secrets
import string
import requests
import logging

logger = logging.getLogger(__name__)


def generate_database_credentials(tenant_slug):
    """Generate secure database credentials for tenant"""
    db_name = f"{tenant_slug}_compliance_db"
    db_user = f"{tenant_slug}_user"
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    password = ''.join(secrets.choice(alphabet) for _ in range(16))
    return db_name, db_user, password


def create_postgresql_database(db_name, db_user, db_password):
    """Create PostgreSQL database and user"""
    conn = psycopg2.connect(
        host=settings.DATABASES['default']['HOST'],
        port=settings.DATABASES['default']['PORT'],
        user=settings.DATABASES['default']['USER'],
        password=settings.DATABASES['default']['PASSWORD'],
        database='postgres'
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = conn.cursor()
    
    try:
        # Drop existing user and database (for clean recreation)
        cursor.execute(f"DROP USER IF EXISTS {db_user};")
        cursor.execute(f"DROP DATABASE IF EXISTS {db_name};")
        
        # Create new user and database
        cursor.execute(f"CREATE USER {db_user} WITH PASSWORD %s;", (db_password,))
        cursor.execute(f"CREATE DATABASE {db_name} OWNER {db_user};")
        cursor.execute(f"GRANT ALL PRIVILEGES ON DATABASE {db_name} TO {db_user};")
        
        print(f"✅ Created database: {db_name}")
        print(f"✅ Created user: {db_user}")
        
    except Exception as e:
        print(f"❌ Error creating database: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


def add_tenant_database_to_django(tenant_info):
    """Add tenant database configuration to Django connections"""
    
    # Start with a copy of the default database configuration
    default_db = settings.DATABASES['default'].copy()
    
    # Update with tenant-specific settings
    db_config = {
        **default_db,  # Copy all default settings
        'NAME': tenant_info.database_name,
        'USER': tenant_info.database_user,
        'PASSWORD': tenant_info.decrypt_password(),
        'HOST': tenant_info.database_host,
        'PORT': tenant_info.database_port,
    }
    
    # Add to Django database connections
    connection_name = f"{tenant_info.tenant_slug}_compliance_db"
    connections.databases[connection_name] = db_config
    
    print(f"✅ Added {connection_name} to Django connections")
    return connection_name


def load_all_tenant_databases():
    """Load all tenant databases into Django connections at startup"""
    
    print("🔄 Loading tenant databases...")
    
    for tenant_info in TenantDatabaseInfo.objects.filter(is_active=True):
        try:
            add_tenant_database_to_django(tenant_info)
            print(f"✅ Loaded: {tenant_info.tenant_slug}")
        except Exception as e:
            print(f"❌ Failed to load {tenant_info.tenant_slug}: {e}")
    
    print("✅ All tenant databases loaded")


def register_tenant_database(tenant_slug, company_name, subscription_plan='BASIC'):
    """Register new tenant database in the system"""
    print(f"\n🏗️  Creating tenant database for: {company_name} ({tenant_slug})")
    
    # Generate credentials
    db_name, db_user, db_password = generate_database_credentials(tenant_slug)
    
    # Create PostgreSQL database and user
    create_postgresql_database(db_name, db_user, db_password)
    
    # Create tenant record
    tenant_info = TenantDatabaseInfo(
        tenant_slug=tenant_slug,
        company_name=company_name,
        database_name=db_name,
        database_user=db_user,
        database_host=settings.DATABASES['default']['HOST'],
        database_port=settings.DATABASES['default']['PORT'],
        subscription_plan=subscription_plan
    )
    
    # Encrypt and save password
    tenant_info.encrypt_password(db_password)
    tenant_info.save()
    
    print(f"✅ Registered tenant: {tenant_slug}")
    
    # Add database to Django connections dynamically
    connection_name = add_tenant_database_to_django(tenant_info)
    
    # Run migrations on tenant database via Service 1
    migration_success = run_tenant_migrations_via_service1(tenant_slug, connection_name)
    
    # Copy templates via Service 1
    template_success = copy_framework_templates_via_service1(tenant_slug)
    
    print(f"🎉 Tenant database setup complete for: {company_name}")
    return {
        'tenant_info': tenant_info,
        'connection_name': connection_name,
        'migration_success': migration_success,
        'template_success': template_success
    }


def run_tenant_migrations_via_service1(tenant_slug, connection_name):
    """Call Service 1 to run migrations on tenant database"""
    try:
        print(f"📞 Calling Service 1 to run migrations for {tenant_slug}")
        
        # Call Service 1 API
        response = requests.post(
            'http://localhost:8000/api/v1/internal/migrate-tenant/',
            json={
                'tenant_slug': tenant_slug,
                'connection_name': connection_name
            },
            headers={'X-Internal-Token': 'service2-secret'},  # TODO: Use proper auth
            timeout=30
        )
        
        if response.status_code == 200:
            print(f"✅ Migrations completed for {tenant_slug}")
            return True
        else:
            print(f"❌ Migration failed for {tenant_slug}: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Failed to call Service 1 for migrations: {e}")
        return False


def copy_framework_templates_via_service1(tenant_slug, framework_ids=None):
    """Call Service 1 to copy framework templates to tenant"""
    try:
        print(f"📞 Calling Service 1 to copy templates to {tenant_slug}")
        
        # Call Service 1 API
        response = requests.post(
            'http://localhost:8000/api/v1/internal/distribute-templates/',
            json={
                'tenant_slug': tenant_slug,
                'framework_ids': framework_ids
            },
            headers={'X-Internal-Token': 'service2-secret'},  # TODO: Use proper auth
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Templates copied to {tenant_slug}: {result.get('frameworks_copied', 0)} frameworks")
            return result
        else:
            print(f"❌ Template copy failed for {tenant_slug}: {response.text}")
            return {}
            
    except Exception as e:
        print(f"❌ Failed to call Service 1 for templates: {e}")
        return {}


def get_tenant_database_credentials(tenant_slug):
    """Get decrypted database credentials for a tenant"""
    try:
        tenant_info = TenantDatabaseInfo.objects.get(
            tenant_slug=tenant_slug, 
            is_active=True
        )
        
        return {
            'database_name': tenant_info.database_name,
            'database_user': tenant_info.database_user,
            'database_password': tenant_info.decrypt_password(),
            'database_host': tenant_info.database_host,
            'database_port': tenant_info.database_port,
            'connection_name': f"{tenant_slug}_compliance_db"
        }
    except TenantDatabaseInfo.DoesNotExist:
        return None


def register_tenant_database_alias_on_demand(tenant_slug):
    """Register tenant database alias on demand (for Service 1)"""
    
    # Check if alias already exists
    connection_name = f"{tenant_slug}_compliance_db"
    if connection_name in connections.databases:
        return connection_name
    
    # Get tenant credentials
    creds = get_tenant_database_credentials(tenant_slug)
    if not creds:
        raise Exception(f"Tenant {tenant_slug} not found")
    
    # Register alias dynamically
    db_config = {
        **settings.DATABASES['default'],
        'NAME': creds['database_name'],
        'USER': creds['database_user'],
        'PASSWORD': creds['database_password'],
        'HOST': creds['database_host'],
        'PORT': creds['database_port'],
    }
    
    connections.databases[connection_name] = db_config
    print(f"✅ Dynamically registered: {connection_name}")
    
    return connection_name