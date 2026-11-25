from django.contrib import admin

from .access import is_school_administrator
from .models import (
    Alert,
    Assessment,
    AttendanceRecord,
    AttendanceSnapshot,
    Classroom,
    Intervention,
    RiskPrediction,
    Student,
    StudentPromotion,
    TeacherActivity,
    TeacherAssignment,
)


@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ('name', 'academic_year', 'term', 'subject')
    search_fields = ('name', 'subject')


class TeacherEnteredDataReadOnlyMixin:
    def has_add_permission(self, request, obj=None):
        return not is_school_administrator(request.user)

    def has_change_permission(self, request, obj=None):
        return not is_school_administrator(request.user)

    def has_delete_permission(self, request, obj=None):
        return not is_school_administrator(request.user)


class AssessmentInline(TeacherEnteredDataReadOnlyMixin, admin.TabularInline):
    model = Assessment
    extra = 0


class AttendanceInline(TeacherEnteredDataReadOnlyMixin, admin.TabularInline):
    model = AttendanceRecord
    extra = 0


class AttendanceSnapshotInline(TeacherEnteredDataReadOnlyMixin, admin.TabularInline):
    model = AttendanceSnapshot
    extra = 0


class StudentPromotionInline(admin.TabularInline):
    model = StudentPromotion
    fk_name = 'student'
    extra = 0
    can_delete = False


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('student_id', 'first_name', 'last_name', 'classroom', 'is_active')
    list_filter = ('classroom', 'is_active', 'gender')
    search_fields = ('student_id', 'first_name', 'last_name')
    inlines = [
        AssessmentInline,
        AttendanceInline,
        AttendanceSnapshotInline,
        StudentPromotionInline,
    ]


@admin.register(Assessment)
class AssessmentAdmin(TeacherEnteredDataReadOnlyMixin, admin.ModelAdmin):
    list_display = ('student', 'subject', 'assessment_type', 'title', 'score', 'date')
    list_filter = ('assessment_type', 'date')
    search_fields = ('student__first_name', 'student__last_name', 'title')


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ('student', 'date', 'status')
    list_filter = ('status', 'date')

    def has_add_permission(self, request):
        return not is_school_administrator(request.user)

    def has_change_permission(self, request, obj=None):
        return not is_school_administrator(request.user)

    def has_delete_permission(self, request, obj=None):
        return not is_school_administrator(request.user)


@admin.register(AttendanceSnapshot)
class AttendanceSnapshotAdmin(admin.ModelAdmin):
    list_display = ('student', 'date', 'attendance_rate')
    list_filter = ('date',)

    def has_add_permission(self, request):
        return not is_school_administrator(request.user)

    def has_change_permission(self, request, obj=None):
        return not is_school_administrator(request.user)

    def has_delete_permission(self, request, obj=None):
        return not is_school_administrator(request.user)


@admin.register(TeacherAssignment)
class TeacherAssignmentAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'classroom', 'subject', 'created_at')
    list_filter = ('classroom', 'subject')
    search_fields = ('teacher__username', 'teacher__first_name', 'teacher__last_name')


@admin.register(StudentPromotion)
class StudentPromotionAdmin(admin.ModelAdmin):
    list_display = ('student', 'from_classroom', 'to_classroom', 'academic_year', 'promoted_at')
    list_filter = ('academic_year', 'promoted_at')
    search_fields = ('student__student_id', 'student__first_name', 'student__last_name')


@admin.register(TeacherActivity)
class TeacherActivityAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'action', 'student', 'classroom', 'created_at')
    list_filter = ('action', 'classroom', 'created_at')
    search_fields = ('teacher__username', 'student__student_id', 'details')


@admin.register(RiskPrediction)
class RiskPredictionAdmin(admin.ModelAdmin):
    list_display = (
        'student',
        'risk_level',
        'failure_probability',
        'average_score',
        'attendance_rate',
        'is_declining',
        'predicted_at',
    )
    list_filter = ('risk_level', 'is_declining')


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ('student', 'alert_type', 'severity', 'is_acknowledged', 'created_at')
    list_filter = ('alert_type', 'severity', 'is_acknowledged')


@admin.register(Intervention)
class InterventionAdmin(admin.ModelAdmin):
    list_display = ('student', 'action', 'suggested_by_system', 'is_completed', 'created_at')
    list_filter = ('action', 'is_completed', 'suggested_by_system')
