"""
URL Configuration for Tenant Management - Service 2
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'tenants', views.TenantManagementViewSet, basename='tenant-management')
router.register(r'distribution', views.FrameworkDistributionViewSet, basename='framework-distribution')

urlpatterns = [
    path('', include(router.urls)),
]