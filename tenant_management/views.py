"""
Tenant Management APIs - Service 2
"""

from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404

from .models import TenantDatabaseInfo
from .tenant_utils import register_tenant_database, copy_framework_templates_via_service1
from rest_framework_simplejwt.authentication import JWTAuthentication
from .tenant_utils import add_tenant_database_to_django, run_tenant_migrations_via_service1
from django.core.exceptions import ValidationError
from .validators import validate_and_normalize_slug




class TenantManagementViewSet(viewsets.ViewSet):
    """
    Tenant Management APIs - Service 2
    Essential for production operations

    """
    permission_classes = [IsAdminUser]
    authentication_classes = [JWTAuthentication]


  # TODO: Add SuperAdminPermission
    
    def list(self, request):
        """List all tenants in the system"""
        tenants = TenantDatabaseInfo.objects.filter(is_active=True).order_by('company_name')
        
        tenant_data = []
        for tenant in tenants:
            tenant_data.append({
                'tenant_slug': tenant.tenant_slug,
                'company_name': tenant.company_name,
                'database_name': tenant.database_name,
                'subscription_plan': tenant.subscription_plan,
                'status': tenant.status,
                'created_at': tenant.created_at,
                'updated_at': tenant.updated_at
            })
        
        return Response({
            'count': len(tenant_data),
            'tenants': tenant_data
        })
    
    def retrieve(self, request, pk=None):
        """Get detailed information about a specific tenant"""
        tenant = get_object_or_404(TenantDatabaseInfo, tenant_slug=pk, is_active=True)
        
        return Response({
            'tenant_slug': tenant.tenant_slug,
            'company_name': tenant.company_name,
            'database_name': tenant.database_name,
            'database_user': tenant.database_user,
            'subscription_plan': tenant.subscription_plan,
            'status': tenant.status,
            'created_at': tenant.created_at,
            'updated_at': tenant.updated_at,
            'stats': {}  # TODO: Get stats from Service 1
        })
    
    @action(detail=False, methods=['post'])
    def create_tenant(self, request):
        """Create new tenant with complete database provisioning"""
        try:
            tenant_slug = validate_and_normalize_slug(request.data.get('tenant_slug'))
        except ValidationError as e:
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        framework_ids = request.data.get('framework_ids', None)
        company_name = request.data.get('company_name')
        subscription_plan = request.data.get('subscription_plan', 'BASIC')
        
        # Validation
        if not tenant_slug or not company_name:
            return Response({
                'success': False,
                'error': 'tenant_slug and company_name are required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if tenant already exists
        existing = TenantDatabaseInfo.objects.filter(tenant_slug=tenant_slug).first()
        if existing:
            # Re-wire idempotently
            connection_name = add_tenant_database_to_django(existing)
            migration_success = run_tenant_migrations_via_service1(tenant_slug, connection_name)
            # template_success = copy_framework_templates_via_service1(tenant_slug)
            template_success = copy_framework_templates_via_service1(tenant_slug, framework_ids)
            return Response({
                'success': True,
                'message': f'Tenant \"{existing.company_name}\" already existed; wiring refreshed.',
                'tenant': {
                    'tenant_slug': existing.tenant_slug,
                    'company_name': existing.company_name,
                    'database_name': existing.database_name,
                    'subscription_plan': existing.subscription_plan,
                    'status': existing.status,
                    'created_at': existing.created_at
                },
                'provisioning': {
                    'connection_name': connection_name,
                    'migration_success': migration_success,
                    'template_success': template_success,
                    'steps': {
                        'generate_credentials': {'ok': True, 'reused': True},
                        'directory_row': {'ok': True, 'reused': True},
                        'postgres_provision': {'ok': True, 'skipped': True},
                        'django_alias': {'ok': True, 'connection_name': connection_name},
                        'migrations': {'ok': bool(migration_success)},
                        'templates': {'ok': bool(template_success), 'summary': template_success},
                        'final_status': existing.status,
                    }
                }
            }, status=status.HTTP_200_OK)

                
        try:
            # Create tenant with complete database provisioning
            result = register_tenant_database(
                tenant_slug=tenant_slug,
                company_name=company_name,
                subscription_plan=subscription_plan,
                framework_ids=framework_ids,
            )
            
            # Extract tenant_info from result
           # Extract tenant_info from result
            tenant_info = result['tenant_info']

            return Response({
                'success': True,
                'message': f'Tenant "{company_name}" created successfully',
                'tenant': {
                    'tenant_slug': tenant_info.tenant_slug,
                    'company_name': tenant_info.company_name,
                    'database_name': tenant_info.database_name,
                    'subscription_plan': tenant_info.subscription_plan,
                    'status': tenant_info.status,
                    'created_at': tenant_info.created_at
                },
                'provisioning': {
                    'connection_name': result['connection_name'],
                    'migration_success': result['migration_success'],
                    'template_success': result['template_success'],
                    'steps': result['steps'],
                }
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({
                'success': False,
                'error': f'Failed to create tenant: {str(e)}'
            }, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['patch'])
    def update_status(self, request, pk=None):
        """Update tenant status (activate, suspend, etc.)"""
        tenant = get_object_or_404(TenantDatabaseInfo, tenant_slug=pk)
        new_status = request.data.get('status')
        
        valid_statuses = ['ACTIVE', 'SUSPENDED', 'INACTIVE']
        if new_status not in valid_statuses:
            return Response({
                'success': False,
                'error': f'Invalid status. Must be one of: {valid_statuses}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        old_status = tenant.status
        tenant.status = new_status
        tenant.save()
        
        return Response({
            'success': True,
            'message': f'Tenant status updated from {old_status} to {new_status}',
            'tenant_slug': tenant.tenant_slug,
            'old_status': old_status,
            'new_status': new_status
        })
    
    @action(detail=True, methods=['delete'])
    def delete_tenant(self, request, pk=None):
        """Delete tenant (soft delete - marks as inactive)"""
        tenant = get_object_or_404(TenantDatabaseInfo, tenant_slug=pk)
        
        # Soft delete
        tenant.is_active = False
        tenant.status = 'INACTIVE'
        tenant.save()
        
        return Response({
            'success': True,
            'message': f'Tenant "{tenant.company_name}" has been deactivated',
            'tenant_slug': tenant.tenant_slug,
            'note': 'Tenant marked as inactive. Database still exists.'
        })


class FrameworkDistributionViewSet(viewsets.ViewSet):
    """Framework Distribution APIs - Service 2"""
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAdminUser]

    
    @action(detail=False, methods=['post'])
    def distribute_to_tenant(self, request):
        """Distribute framework templates to specific tenant via Service 1"""
        try:
            tenant_slug = validate_and_normalize_slug(request.data.get('tenant_slug'))
        except ValidationError as e:
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        framework_ids = request.data.get('framework_ids', None)
        
        
        if not tenant_slug:
            return Response({
                'success': False,
                'error': 'tenant_slug is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Verify tenant exists
        tenant = get_object_or_404(TenantDatabaseInfo, tenant_slug=tenant_slug, is_active=True)
        
        try:
            result = copy_framework_templates_via_service1(
                tenant_slug=tenant_slug,
                framework_ids=framework_ids
            )
            
            return Response({
                'success': True,
                'tenant_slug': tenant_slug,
                'company_name': tenant.company_name,
                'message': 'Distribution request sent to Service 1',
                'note': 'Check Service 1 logs for actual distribution results'
            })
            
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)