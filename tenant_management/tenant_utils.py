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
from psycopg2 import sql


logger = logging.getLogger(__name__)


def generate_database_credentials(tenant_slug):
    """Generate secure database credentials for tenant"""
    db_name = f"{tenant_slug}_compliance_db"
    db_user = f"{tenant_slug}_user"
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    password = ''.join(secrets.choice(alphabet) for _ in range(16))
    return db_name, db_user, password


def create_postgresql_database(db_name, db_user, db_password):
    """
    Idempotent: create-if-missing user & database, no drops.
    - If role exists: ALTER ROLE to (re)set password & LOGIN
    - If DB exists: ensure owner is db_user and grant privileges
    """
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
        # 1) ROLE / USER
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s;", (db_user,))
        role_exists = cursor.fetchone() is not None

        if not role_exists:
            cursor.execute(
                sql.SQL("CREATE USER {} WITH PASSWORD %s")
                .format(sql.Identifier(db_user)),
                (db_password,)
            )

            print(f"✅ Created database user: {db_user}")
        else:
            cursor.execute(
                sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD %s")
                .format(sql.Identifier(db_user)),
                (db_password,)
            )

            print(f"🔁 Updated password for user: {db_user}")

        # 2) DATABASE
        cursor.execute("SELECT 1 FROM pg_database WHERE datname=%s;", (db_name,))
        db_exists = cursor.fetchone() is not None

        if not db_exists:
            cursor.execute(
                    sql.SQL("CREATE DATABASE {} OWNER {}")
                    .format(sql.Identifier(db_name), sql.Identifier(db_user))
                )

            print(f"✅ Created database: {db_name}")
        else:
            # Ensure owner is correct (requires superuser)
            cursor.execute("""
                SELECT pg_catalog.pg_get_userbyid(datdba)
                FROM pg_database WHERE datname=%s;
            """, (db_name,))
            current_owner = cursor.fetchone()[0]
            if current_owner != db_user:
                cursor.execute(
                    sql.SQL("ALTER DATABASE {} OWNER TO {}")
                    .format(sql.Identifier(db_name), sql.Identifier(db_user))
                )

                print(f"🔁 Changed owner of {db_name} to {db_user}")

        # 3) privileges (harmless if re-run)
        cursor.execute(
            sql.SQL("GRANT ALL PRIVILEGES ON DATABASE {} TO {}")
            .format(sql.Identifier(db_name), sql.Identifier(db_user))
        )

        print(f"✅ Granted privileges to {db_user} on {db_name}")

    except Exception as e:
        print(f"❌ Error creating/updating database: {e}")
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

def register_tenant_database(tenant_slug, company_name, subscription_plan='BASIC', framework_ids=None):
    """Register and provision a tenant database with step-by-step status/ledger."""
    print(f"\n🏗️  Creating tenant database for: {company_name} ({tenant_slug})")

    steps = {
        'generate_credentials': None,
        'directory_row': None,
        'postgres_provision': None,
        'django_alias': None,
        'migrations': None,
        'templates': None,
        'final_status': None,
    }

    # 1) credentials
    db_name, db_user, db_password = generate_database_credentials(tenant_slug)
    steps['generate_credentials'] = {'ok': True, 'db_name': db_name, 'db_user': db_user}

    # 2) create directory row first, mark as PROVISIONING
    tenant_info = TenantDatabaseInfo(
        tenant_slug=tenant_slug,
        company_name=company_name,
        database_name=db_name,
        database_user=db_user,
        database_host=settings.DATABASES['default']['HOST'],
        database_port=settings.DATABASES['default']['PORT'],
        subscription_plan=subscription_plan,
        status='PROVISIONING',
        is_active=True,
    )
    tenant_info.encrypt_password(db_password)
    tenant_info.save()
    steps['directory_row'] = {'ok': True, 'id': str(tenant_info.id)}

    try:
        # 3) ensure postgres role/db
        create_postgresql_database(db_name, db_user, db_password)
        steps['postgres_provision'] = {'ok': True}

        # 4) wire alias
        connection_name = add_tenant_database_to_django(tenant_info)
        steps['django_alias'] = {'ok': True, 'connection_name': connection_name}

        # 5) migrations (service 1)
        migration_success = run_tenant_migrations_via_service1(tenant_slug, connection_name)
        steps['migrations'] = {'ok': bool(migration_success)}

        # 6) template copy (service 1)
        template_result = copy_framework_templates_via_service1(tenant_slug, framework_ids)
        template_ok = bool(template_result) and template_result.get('success') is True
        steps['templates'] = {'ok': template_ok, 'summary': template_result}

        # 7) final status
        all_ok = steps['postgres_provision']['ok'] and steps['django_alias']['ok'] and steps['migrations']['ok'] and steps['templates']['ok']
        tenant_info.status = 'ACTIVE' if all_ok else 'PROVISIONING_FAILED'
        tenant_info.save()
        steps['final_status'] = tenant_info.status

        print(f"🎉 Tenant database setup complete for: {company_name}")

        return {
            'tenant_info': tenant_info,
            'connection_name': connection_name,
            'migration_success': migration_success,
            'template_success': template_result,
            'steps': steps,
        }

    except Exception as e:
        # on any exception mark failure
        tenant_info.status = 'PROVISIONING_FAILED'
        tenant_info.save()
        steps['final_status'] = 'PROVISIONING_FAILED'
        steps['error'] = str(e)
        print(f"❌ Provisioning error: {e}")
        # bubble up so the API returns 400 with the error
        raise


def run_tenant_migrations_via_service1(tenant_slug, connection_name):
    """Call Service 1 to run migrations on tenant database"""
    try:
        print(f"📞 Calling Service 1 to run migrations for {tenant_slug}")
        
        # Call Service 1 API
        service1 = settings.SERVICE1_URL.rstrip('/')
        response = requests.post(
            f'{service1}/api/v1/internal/migrate-tenant/',
            json={'tenant_slug': tenant_slug, 'connection_name': connection_name},
            headers={'X-Internal-Token': settings.INTERNAL_REGISTER_DB_TOKEN},
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
        # response = requests.post(
        #     'http://localhost:8000/api/v1/internal/distribute-templates/',
        #     json={
        #         'tenant_slug': tenant_slug,
        #         'framework_ids': framework_ids
        #     },
        #     headers={'X-Internal-Token': 'service2-secret'},  # TODO: Use proper auth
        #     timeout=60
        # )
        
        service1 = settings.SERVICE1_URL.rstrip('/')
        response = requests.post(
            f'{service1}/api/v1/internal/distribute-templates/',
            json={'tenant_slug': tenant_slug, 'framework_ids': framework_ids},
            headers={'X-Internal-Token': settings.INTERNAL_REGISTER_DB_TOKEN},
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