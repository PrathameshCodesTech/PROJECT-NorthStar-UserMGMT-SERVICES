"""
Internal API URLs for Service 2 - Inter-service communication only
"""

from django.urls import path
from .internal_views import InternalTenantCredentialsView, InternalTenantHealthView

urlpatterns = [
    path('tenants/<str:tenant_slug>/credentials/', 
         InternalTenantCredentialsView.as_view(), 
         name='internal-tenant-credentials'),
    
    path('tenants/<str:tenant_slug>/health/', 
         InternalTenantHealthView.as_view(), 
         name='internal-tenant-health'),
]