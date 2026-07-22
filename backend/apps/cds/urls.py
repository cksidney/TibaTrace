from rest_framework.routers import SimpleRouter

from apps.cds.api import ClinicalEvaluationViewSet, KnowledgeReleaseViewSet

router = SimpleRouter()
router.register("evaluations", ClinicalEvaluationViewSet, basename="cds-evaluation")
router.register("knowledge-releases", KnowledgeReleaseViewSet, basename="cds-knowledge-release")
urlpatterns = router.urls
