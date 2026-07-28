from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PosClinicalOverrideViewSet, PosClinicalScreeningViewSet

router = DefaultRouter()
router.register('overrides', PosClinicalOverrideViewSet, basename='pos-clinical-override')
router.register('', PosClinicalScreeningViewSet, basename='pos-clinical-screening')

urlpatterns = [
    path('', include(router.urls)),
]
