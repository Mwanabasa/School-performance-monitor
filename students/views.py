from django.utils import timezone
from django.db.models import F, Prefetch
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from .importers import import_students_from_excel
from .access import (
    assigned_classrooms,
    assigned_students,
    is_school_administrator,
    is_teacher,
    record_teacher_activity,
    teacher_has_classroom,
    teacher_has_subject,
    teacher_assignments,
)
from analytics.risk_service import predict_student, run_batch_predictions
from .models import (
    Alert,
    Assessment,
    AttendanceRecord,
    AttendanceSnapshot,
    Classroom,
    Intervention,
    RiskPrediction,
    Student,
)
from .permissions import IsSchoolAdministrator, IsTeacher
from .serializers import (
    AlertSerializer,
    AssessmentSerializer,
    AttendanceRecordSerializer,
    AttendanceSnapshotSerializer,
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

    def get_queryset(self):
        if is_school_administrator(self.request.user):
            return self.queryset
        if is_teacher(self.request.user):
            return assigned_classrooms(self.request.user)
        return self.queryset.none()

    def get_permissions(self):
        if self.action in {'create', 'update', 'partial_update', 'destroy'}:
            return [IsSchoolAdministrator()]
        return super().get_permissions()


class StudentViewSet(viewsets.ModelViewSet):
    queryset = Student.objects.select_related('classroom').prefetch_related('risk_predictions')
    search_fields = ['student_id', 'first_name', 'last_name']
    filterset_fields = ['classroom', 'is_active', 'gender']
    ordering_fields = ['last_name', 'first_name', 'student_id']

    def get_queryset(self):
        if is_school_administrator(self.request.user):
            return self.queryset
        if is_teacher(self.request.user):
            visible_assessments = Assessment.objects.filter(
                student__classroom__teacher_assignments__teacher=self.request.user,
                subject=F('student__classroom__teacher_assignments__subject'),
            ).distinct()
            return assigned_students(self.request.user).select_related(
                'classroom'
            ).prefetch_related(
                'risk_predictions',
                Prefetch('assessments', queryset=visible_assessments),
            )
        return self.queryset.none()

    def get_permissions(self):
        if self.action == 'import_excel':
            return [IsTeacher()]
        return super().get_permissions()

    def perform_create(self, serializer):
        classroom = serializer.validated_data.get('classroom')
        if is_teacher(self.request.user) and (
            classroom is None or not teacher_has_classroom(self.request.user, classroom)
        ):
            raise PermissionDenied('You can only add students to your assigned classrooms.')
        student = serializer.save()
        record_teacher_activity(
            self.request.user,
            'student_registered',
            'Student record added through the API.',
            student=student,
        )

    def perform_update(self, serializer):
        classroom = serializer.validated_data.get(
            'classroom',
            serializer.instance.classroom,
        )
        if is_teacher(self.request.user) and (
            classroom is None or not teacher_has_classroom(self.request.user, classroom)
        ):
            raise PermissionDenied('You can only assign students to your assigned classrooms.')
        student = serializer.save()
        record_teacher_activity(
            self.request.user,
            'student_updated',
            'Student information updated through the API.',
            student=student,
        )

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
            classrooms = (
                None
                if is_school_administrator(request.user)
                else assigned_classrooms(request.user)
            )
            allowed_subjects = None
            if classrooms is not None:
                allowed_subjects = {}
                for assignment in teacher_assignments(request.user):
                    allowed_subjects.setdefault(assignment.classroom_id, set()).add(
                        assignment.subject
                    )
            result = import_students_from_excel(
                upload,
                allowed_classrooms=classrooms,
                allowed_subjects=allowed_subjects,
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        record_teacher_activity(
            request.user,
            'student_import',
            f"Imported {result['rows_processed']} rows via API.",
        )
        run_batch_predictions(students=assigned_students(request.user))
        return Response(result)

    @action(detail=True, methods=['get'])
    def timeline(self, request, pk=None):
        student = self.get_object()
        assessments = student.assessments.order_by('date')
        if is_teacher(request.user):
            assigned_subjects = teacher_assignments(request.user).filter(
                classroom=student.classroom
            ).values('subject')
            assessments = assessments.filter(subject__in=assigned_subjects)
        assessments = assessments.values(
            'date', 'assessment_type', 'title', 'score', 'max_score'
        )
        return Response(list(assessments))


class AssessmentViewSet(viewsets.ModelViewSet):
    queryset = Assessment.objects.select_related('student')
    serializer_class = AssessmentSerializer
    filterset_fields = ['student', 'assessment_type', 'date']
    ordering_fields = ['date', 'score']

    def _ensure_assigned_student(self, student, subject):
        if is_teacher(self.request.user):
            if (
                student.classroom_id is None
                or not teacher_has_subject(self.request.user, student.classroom, subject)
            ):
                raise PermissionDenied(
                    'You can only manage assessments for subjects assigned to you in this class.'
                )

    def get_queryset(self):
        if is_school_administrator(self.request.user):
            return self.queryset
        return self.queryset.filter(
            student__classroom__teacher_assignments__teacher=self.request.user,
            subject=F('student__classroom__teacher_assignments__subject'),
        ).distinct()

    def get_permissions(self):
        if self.action in {'create', 'update', 'partial_update', 'destroy'}:
            return [IsTeacher()]
        return super().get_permissions()

    def _refresh_student(self, assessment):
        if assessment.assessment_type == Assessment.AssessmentType.ENDTERM:
            run_batch_predictions(students=assigned_students(self.request.user))
        else:
            predict_student(assessment.student)

    def perform_create(self, serializer):
        student = serializer.validated_data['student']
        self._ensure_assigned_student(
            student,
            serializer.validated_data.get('subject', ''),
        )
        assessment = serializer.save()
        record_teacher_activity(
            self.request.user,
            'assessment_recorded',
            f'{assessment.subject} — {assessment.get_assessment_type_display()}: {assessment.title}.',
            student=assessment.student,
        )
        self._refresh_student(assessment)

    def perform_update(self, serializer):
        student = serializer.validated_data.get('student', serializer.instance.student)
        subject = serializer.validated_data.get('subject', serializer.instance.subject)
        self._ensure_assigned_student(student, subject)
        assessment = serializer.save()
        record_teacher_activity(
            self.request.user,
            'assessment_recorded',
            f'{assessment.subject} — {assessment.get_assessment_type_display()} updated: {assessment.title}.',
            student=assessment.student,
        )
        self._refresh_student(assessment)


class AttendanceRecordViewSet(viewsets.ModelViewSet):
    queryset = AttendanceRecord.objects.select_related('student')
    serializer_class = AttendanceRecordSerializer
    filterset_fields = ['student', 'status', 'date']

    def get_permissions(self):
        if self.action in {'create', 'update', 'partial_update', 'destroy'}:
            return [IsTeacher()]
        return super().get_permissions()

    def get_queryset(self):
        if is_school_administrator(self.request.user):
            return self.queryset
        return self.queryset.filter(
            student__classroom__teacher_assignments__teacher=self.request.user
        ).distinct()

    def perform_create(self, serializer):
        student = serializer.validated_data['student']
        if is_teacher(self.request.user) and not teacher_has_classroom(
            self.request.user, student.classroom
        ):
            raise PermissionDenied('You can only manage attendance for your assigned students.')
        record = serializer.save()
        record_teacher_activity(
            self.request.user,
            'attendance_recorded',
            f'{record.date}: {record.get_status_display()}.',
            student=record.student,
        )
        predict_student(record.student)

    def perform_update(self, serializer):
        student = serializer.validated_data.get('student', serializer.instance.student)
        if is_teacher(self.request.user) and not teacher_has_classroom(
            self.request.user, student.classroom
        ):
            raise PermissionDenied('You can only manage attendance for your assigned students.')
        record = serializer.save()
        record_teacher_activity(
            self.request.user,
            'attendance_recorded',
            f'{record.date}: {record.get_status_display()} updated.',
            student=record.student,
        )
        predict_student(record.student)


class AttendanceSnapshotViewSet(viewsets.ModelViewSet):
    queryset = AttendanceSnapshot.objects.select_related('student')
    serializer_class = AttendanceSnapshotSerializer
    filterset_fields = ['student', 'date']
    ordering_fields = ['date', 'attendance_rate']

    def get_permissions(self):
        if self.action in {'create', 'update', 'partial_update', 'destroy'}:
            return [IsTeacher()]
        return super().get_permissions()

    def get_queryset(self):
        if is_school_administrator(self.request.user):
            return self.queryset
        return self.queryset.filter(
            student__classroom__teacher_assignments__teacher=self.request.user
        ).distinct()

    def perform_create(self, serializer):
        student = serializer.validated_data['student']
        if is_teacher(self.request.user) and not teacher_has_classroom(
            self.request.user, student.classroom
        ):
            raise PermissionDenied('You can only manage attendance for your assigned students.')
        snapshot = serializer.save()
        record_teacher_activity(
            self.request.user,
            'attendance_recorded',
            f'Attendance rate recorded: {snapshot.attendance_rate:.0%}.',
            student=snapshot.student,
        )
        predict_student(snapshot.student)

    def perform_update(self, serializer):
        student = serializer.validated_data.get('student', serializer.instance.student)
        if is_teacher(self.request.user) and not teacher_has_classroom(
            self.request.user, student.classroom
        ):
            raise PermissionDenied('You can only manage attendance for your assigned students.')
        snapshot = serializer.save()
        record_teacher_activity(
            self.request.user,
            'attendance_recorded',
            f'Attendance rate updated: {snapshot.attendance_rate:.0%}.',
            student=snapshot.student,
        )
        predict_student(snapshot.student)


class RiskPredictionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RiskPrediction.objects.select_related('student')
    serializer_class = RiskPredictionSerializer
    filterset_fields = ['student', 'risk_level', 'is_declining']

    def get_queryset(self):
        if is_school_administrator(self.request.user):
            return self.queryset
        return self.queryset.filter(
            student__classroom__teacher_assignments__teacher=self.request.user
        ).distinct()


class AlertViewSet(viewsets.ModelViewSet):
    queryset = Alert.objects.select_related('student')
    serializer_class = AlertSerializer
    filterset_fields = ['student', 'alert_type', 'severity', 'is_acknowledged']

    def get_queryset(self):
        if is_school_administrator(self.request.user):
            return self.queryset
        return self.queryset.filter(
            student__classroom__teacher_assignments__teacher=self.request.user
        ).distinct()

    def perform_create(self, serializer):
        student = serializer.validated_data['student']
        if is_teacher(self.request.user) and not teacher_has_classroom(
            self.request.user, student.classroom
        ):
            raise PermissionDenied('You can only manage alerts for your assigned students.')
        serializer.save()

    def perform_update(self, serializer):
        student = serializer.validated_data.get('student', serializer.instance.student)
        if is_teacher(self.request.user) and not teacher_has_classroom(
            self.request.user, student.classroom
        ):
            raise PermissionDenied('You can only manage alerts for your assigned students.')
        serializer.save()

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

    def get_queryset(self):
        if is_school_administrator(self.request.user):
            return self.queryset
        return self.queryset.filter(
            student__classroom__teacher_assignments__teacher=self.request.user
        ).distinct()

    def perform_create(self, serializer):
        student = serializer.validated_data['student']
        if is_teacher(self.request.user) and not teacher_has_classroom(
            self.request.user, student.classroom
        ):
            raise PermissionDenied(
                'You can only manage interventions for your assigned students.'
            )
        serializer.save()

    def perform_update(self, serializer):
        student = serializer.validated_data.get('student', serializer.instance.student)
        if is_teacher(self.request.user) and not teacher_has_classroom(
            self.request.user, student.classroom
        ):
            raise PermissionDenied(
                'You can only manage interventions for your assigned students.'
            )
        serializer.save()

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
