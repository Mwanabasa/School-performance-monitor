from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from .importers import import_students_from_excel
from .models import (
    Alert,
    Assessment,
    AttendanceRecord,
    Classroom,
    Intervention,
    RiskPrediction,
    Student,
)
from .serializers import (
    AlertSerializer,
    AssessmentSerializer,
    AttendanceRecordSerializer,
    ClassroomSerializer,
    InterventionSerializer,
    RiskPredictionSerializer,
    StudentDetailSerializer,
    StudentSerializer,
)


class ClassroomViewSet(viewsets.ModelViewSet):
    queryset = Classroom.objects.all()
    serializer_class = ClassroomSerializer
    search_fields = ['name', 'subject']


class StudentViewSet(viewsets.ModelViewSet):
    queryset = Student.objects.select_related('classroom').prefetch_related('risk_predictions')
    search_fields = ['student_id', 'first_name', 'last_name']
    filterset_fields = ['classroom', 'is_active', 'gender']
    ordering_fields = ['last_name', 'first_name', 'student_id']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return StudentDetailSerializer
        return StudentSerializer

    @action(detail=False, methods=['post'], parser_classes=[MultiPartParser, FormParser])
    def import_excel(self, request):
        upload = request.FILES.get('file')
        if not upload:
            return Response({'detail': 'Upload an Excel/CSV file as "file".'}, status=400)
        try:
            result = import_students_from_excel(upload)
        except Exception as exc:
            return Response({'detail': str(exc)}, status=400)
        return Response(result)

    @action(detail=True, methods=['get'])
    def timeline(self, request, pk=None):
        student = self.get_object()
        assessments = student.assessments.order_by('date').values(
            'date', 'assessment_type', 'title', 'score', 'max_score'
        )
        return Response(list(assessments))


class AssessmentViewSet(viewsets.ModelViewSet):
    queryset = Assessment.objects.select_related('student')
    serializer_class = AssessmentSerializer
    filterset_fields = ['student', 'assessment_type', 'date']
    ordering_fields = ['date', 'score']


class AttendanceRecordViewSet(viewsets.ModelViewSet):
    queryset = AttendanceRecord.objects.select_related('student')
    serializer_class = AttendanceRecordSerializer
    filterset_fields = ['student', 'status', 'date']


class RiskPredictionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RiskPrediction.objects.select_related('student')
    serializer_class = RiskPredictionSerializer
    filterset_fields = ['student', 'risk_level', 'is_declining']


class AlertViewSet(viewsets.ModelViewSet):
    queryset = Alert.objects.select_related('student')
    serializer_class = AlertSerializer
    filterset_fields = ['student', 'alert_type', 'severity', 'is_acknowledged']

    @action(detail=True, methods=['post'])
    def acknowledge(self, request, pk=None):
        alert = self.get_object()
        alert.is_acknowledged = True
        alert.acknowledged_at = timezone.now()
        alert.save(update_fields=['is_acknowledged', 'acknowledged_at'])
        return Response(AlertSerializer(alert).data)


class InterventionViewSet(viewsets.ModelViewSet):
    queryset = Intervention.objects.select_related('student')
    serializer_class = InterventionSerializer
    filterset_fields = ['student', 'action', 'is_completed', 'suggested_by_system']

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        intervention = self.get_object()
        intervention.is_completed = True
        intervention.completed_at = timezone.now()
        notes = request.data.get('notes')
        if notes:
            intervention.notes = notes
        intervention.save()
        return Response(InterventionSerializer(intervention).data)
