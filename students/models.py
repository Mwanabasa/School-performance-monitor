from django.core.validators import MaxValueValidator, MinValueValidator
from django.conf import settings
from django.db import models
from django.utils import timezone


def current_academic_year():
    return str(timezone.localdate().year)


class Classroom(models.Model):
    name = models.CharField(max_length=100)
    academic_year = models.CharField(max_length=20, default=current_academic_year)
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


class TeacherAssignment(models.Model):
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='class_assignments',
    )
    classroom = models.ForeignKey(
        Classroom,
        on_delete=models.CASCADE,
        related_name='teacher_assignments',
    )
    subject = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['classroom__name', 'subject', 'teacher__username']
        unique_together = [('teacher', 'classroom', 'subject')]

    def __str__(self):
        return f'{self.teacher.get_full_name() or self.teacher.username} — {self.classroom.name}: {self.subject}'


class StudentPromotion(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='promotions')
    from_classroom = models.ForeignKey(
        Classroom,
        on_delete=models.PROTECT,
        related_name='promotions_from',
        null=True,
        blank=True,
    )
    to_classroom = models.ForeignKey(
        Classroom,
        on_delete=models.PROTECT,
        related_name='promotions_to',
    )
    promoted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='student_promotions',
        null=True,
        blank=True,
    )
    promoted_at = models.DateField(default=timezone.localdate)
    academic_year = models.CharField(max_length=20)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-promoted_at', '-id']

    def __str__(self):
        return f'{self.student} promoted to {self.to_classroom.name} on {self.promoted_at}'


class TeacherActivity(models.Model):
    class Action(models.TextChoices):
        STUDENT_REGISTERED = 'student_registered', 'Registered student'
        STUDENT_UPDATED = 'student_updated', 'Updated student'
        ASSESSMENT_RECORDED = 'assessment_recorded', 'Recorded assessment'
        ATTENDANCE_RECORDED = 'attendance_recorded', 'Recorded attendance'
        STUDENT_IMPORT = 'student_import', 'Imported student data'

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='teacher_activity',
    )
    student = models.ForeignKey(
        Student,
        on_delete=models.SET_NULL,
        related_name='teacher_activities',
        null=True,
        blank=True,
    )
    classroom = models.ForeignKey(
        Classroom,
        on_delete=models.SET_NULL,
        related_name='teacher_activities',
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=50, choices=Action.choices)
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.teacher.username}: {self.action}'


class Assessment(models.Model):
    class AssessmentType(models.TextChoices):
        QUIZ = 'quiz', 'Quiz'
        TEST = 'test', 'Test'
        ASSIGNMENT = 'assignment', 'Assignment'
        PROJECT = 'project', 'Project'
        MIDTERM = 'midterm', 'Midterm Examination'
        ENDTERM = 'endterm', 'End-of-Term Examination'
        OTHER = 'other', 'Other'

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='assessments')
    subject = models.CharField(max_length=100, blank=True, default='')
    academic_year = models.CharField(max_length=20, blank=True, default='')
    term = models.CharField(max_length=20, blank=True, default='')
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

    def save(self, *args, **kwargs):
        updated_fields = set(kwargs.get('update_fields', ()))
        if self.student_id and (not self.academic_year or not self.term):
            classroom = self.student.classroom
            if classroom:
                if not self.academic_year:
                    self.academic_year = classroom.academic_year
                    updated_fields.add('academic_year')
                if not self.term:
                    self.term = classroom.term
                    updated_fields.add('term')
        if 'update_fields' in kwargs and updated_fields:
            kwargs['update_fields'] = updated_fields
        super().save(*args, **kwargs)

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


class AttendanceSnapshot(models.Model):
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='attendance_snapshots'
    )
    attendance_rate = models.FloatField(
        validators=[MinValueValidator(0), MaxValueValidator(1)]
    )
    date = models.DateField(default=timezone.localdate)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']
        unique_together = [('student', 'date')]

    def __str__(self):
        return f'{self.student} — {self.date}: {self.attendance_rate:.0%} attendance'


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
