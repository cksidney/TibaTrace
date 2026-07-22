from rest_framework.routers import SimpleRouter

from apps.documents.api import StoredClinicalDocumentViewSet

router = SimpleRouter()
router.register("", StoredClinicalDocumentViewSet, basename="stored-document")
urlpatterns = router.urls
