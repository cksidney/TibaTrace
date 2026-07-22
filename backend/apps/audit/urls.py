from rest_framework.routers import SimpleRouter

from apps.audit.api import AuditEventViewSet

router = SimpleRouter()
router.register("events", AuditEventViewSet, basename="audit-event")
urlpatterns = router.urls
