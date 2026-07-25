from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PosClinicalScreeningViewSet

router = DefaultRouter()
router.register('', PosClinicalScreeningViewSet, basename='pos-clinical-screening')

urlpatterns = [
    path('', include(router.urls)),
]
