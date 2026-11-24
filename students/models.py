from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class Classroom(models.Model):
    name = models.CharField(max_length=100)
    academic_year = models.CharField(max_length=20, default='2025')
    term = models.CharField(max_length=20, default='Term 1')
    subject = models.CharField(max_length=100, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.academic_year} {self.term})'


class Student(models.Model):
    class Gender(models.TextChoices):
        MALE = 'M', 'Male'
        FEMALE = 'F', 'Female'
        OTHER = 'O', 'Other'

    student_id = models.CharField(max_length=50, unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    gender = models.CharField(max_length=1, choices=Gender.choices, blank=True)
    classroom = models.ForeignKey(
        Classroom, on_delete=models.SET_NULL, null=True, blank=True, related_name='students'
    )
    date_of_birth = models.DateField(null=True, blank=True)
    guardian_name = models.CharField(max_length=150, blank=True)
    guardian_phone = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return f'{self.first_name} {self.last_name} ({self.student_id})'

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'


class Assessment(models.Model):
    class AssessmentType(models.TextChoices):
        TEST = 'test', 'Test'
        ASSIGNMENT = 'assignment', 'Assignment'
        PROJECT = 'project', 'Project'
        MIDTERM = 'midterm', 'Midterm Examination'
        ENDTERM = 'endterm', 'End-of-Term Examination'
        OTHER = 'other', 'Other'

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='assessments')
    assessment_type = models.CharField(max_length=20, choices=AssessmentType.choices)
    title = models.CharField(max_length=150)
    score = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(100)])
    max_score = models.FloatField(default=100, validators=[MinValueValidator(1)])
    date = models.DateField(default=timezone.localdate)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date', 'id']

    def __str__(self):
        return f'{self.student} — {self.title} ({self.score})'

    @property
    def percentage(self):
        if self.max_score <= 0:
            return 0.0
        return round((self.score / self.max_score) * 100, 2)


class AttendanceRecord(models.Model):
    class Status(models.TextChoices):
        PRESENT = 'present', 'Present'
        ABSENT = 'absent', 'Absent'
        LATE = 'late', 'Late'
        EXCUSED = 'excused', 'Excused'

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='attendance_records')
    date = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PRESENT)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-date']
        unique_together = [('student', 'date')]

    def __str__(self):
        return f'{self.student} — {self.date}: {self.status}'


class RiskPrediction(models.Model):
    class RiskLevel(models.TextChoices):
        LOW = 'low', 'Low'
        MEDIUM = 'medium', 'Medium'
        HIGH = 'high', 'High'

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='risk_predictions')
    failure_probability = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(1)])
    risk_level = models.CharField(max_length=10, choices=RiskLevel.choices)
    average_score = models.FloatField(null=True, blank=True)
    attendance_rate = models.FloatField(null=True, blank=True)
    trend_slope = models.FloatField(null=True, blank=True)
    is_declining = models.BooleanField(default=False)
    features_snapshot = models.JSONField(default=dict, blank=True)
    model_version = models.CharField(max_length=50, blank=True, default='v1')
    predicted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-predicted_at']
        get_latest_by = 'predicted_at'

    def __str__(self):
        return f'{self.student}: {self.risk_level} ({self.failure_probability:.0%})'


class Alert(models.Model):
    class AlertType(models.TextChoices):
        HIGH_RISK = 'high_risk', 'High Failure Risk'
        DECLINE = 'decline', 'Performance Decline'
        ATTENDANCE = 'attendance', 'Low Attendance'
        THRESHOLD = 'threshold', 'Risk Threshold Crossed'

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='alerts')
    alert_type = models.CharField(max_length=20, choices=AlertType.choices)
    message = models.TextField()
    severity = models.CharField(
        max_length=10,
        choices=RiskPrediction.RiskLevel.choices,
        default=RiskPrediction.RiskLevel.MEDIUM,
    )
    is_acknowledged = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.severity}] {self.student}: {self.alert_type}'


class Intervention(models.Model):
    class Action(models.TextChoices):
        REMEDIAL = 'remedial', 'Remedial lessons'
        EXTRA_ASSIGNMENT = 'extra_assignment', 'Extra assignments'
        ATTENDANCE_FOLLOWUP = 'attendance_followup', 'Attendance follow-up'
        CONSULTATION = 'consultation', 'Individual consultation'
        GUARDIAN_MEETING = 'guardian_meeting', 'Guardian meeting'
        PEER_TUTORING = 'peer_tutoring', 'Peer tutoring'
        OTHER = 'other', 'Other'

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='interventions')
    action = models.CharField(max_length=30, choices=Action.choices)
    reason = models.TextField()
    suggested_by_system = models.BooleanField(default=True)
    is_completed = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.student}: {self.get_action_display()}'
