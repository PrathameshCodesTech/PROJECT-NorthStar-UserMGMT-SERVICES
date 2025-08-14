"""
Internal APIs for inter-service communication - Service 2
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from .models import TenantDatabaseInfo
from .tenant_utils import get_tenant_database_credentials, register_tenant_database_alias_on_demand


class InternalTenantCredentialsView(APIView):
    """
    Internal API for Service 1 to get tenant database credentials
    NEVER expose this publicly - only for service-to-service communication
    """
    
    def get(self, request, tenant_slug):
        """Get decrypted database credentials for a tenant"""
        
        # TODO: Verify internal token
        internal_token = request.headers.get('X-Internal-Token')
        if internal_token != 'service2-secret':  # TODO: Use proper auth
            return Response(
                {'error': 'Unauthorized - Internal API only'}, 
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # Get tenant credentials
        creds = get_tenant_database_credentials(tenant_slug)
        if not creds:
            return Response(
                {'error': f'Tenant {tenant_slug} not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        return Response({
            'success': True,
            'tenant_slug': tenant_slug,
            'credentials': creds
        })


class InternalTenantHealthView(APIView):
    """Check health of a tenant database connection"""
    
    def post(self, request, tenant_slug):
        """Test tenant database connection"""
        
        # TODO: Verify internal token
        internal_token = request.headers.get('X-Internal-Token')
        if internal_token != 'service2-secret':
            return Response(
                {'error': 'Unauthorized'}, 
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        try:
            # Register alias if needed
            connection_name = register_tenant_database_alias_on_demand(tenant_slug)
            
            # Test connection
            from django.db import connections
            with connections[connection_name].cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
            
            return Response({
                'success': True,
                'tenant_slug': tenant_slug,
                'connection_name': connection_name,
                'status': 'healthy',
                'test_result': result[0] if result else None
            })
            
        except Exception as e:
            return Response({
                'success': False,
                'tenant_slug': tenant_slug,
                'status': 'unhealthy',
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)