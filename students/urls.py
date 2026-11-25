from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AlertViewSet,
    AssessmentViewSet,
    AttendanceRecordViewSet,
    AttendanceSnapshotViewSet,
    ClassroomViewSet,
    InterventionViewSet,
    RiskPredictionViewSet,
    StudentViewSet,
)

router = DefaultRouter()
router.register('classrooms', ClassroomViewSet)
router.register('students', StudentViewSet)
router.register('assessments', AssessmentViewSet)
router.register('attendance', AttendanceRecordViewSet)
router.register('attendance-snapshots', AttendanceSnapshotViewSet)
router.register('predictions', RiskPredictionViewSet)
router.register('alerts', AlertViewSet)
router.register('interventions', InterventionViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
