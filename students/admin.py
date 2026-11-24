from django.contrib import admin

from .models import (
    Alert,
    Assessment,
    AttendanceRecord,
    Classroom,
    Intervention,
    RiskPrediction,
    Student,
)


@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ('name', 'academic_year', 'term', 'subject')
    search_fields = ('name', 'subject')


class AssessmentInline(admin.TabularInline):
    model = Assessment
    extra = 0


class AttendanceInline(admin.TabularInline):
    model = AttendanceRecord
    extra = 0


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('student_id', 'first_name', 'last_name', 'classroom', 'is_active')
    list_filter = ('classroom', 'is_active', 'gender')
    search_fields = ('student_id', 'first_name', 'last_name')
    inlines = [AssessmentInline, AttendanceInline]


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = ('student', 'assessment_type', 'title', 'score', 'date')
    list_filter = ('assessment_type', 'date')
    search_fields = ('student__first_name', 'student__last_name', 'title')


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ('student', 'date', 'status')
    list_filter = ('status', 'date')


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
