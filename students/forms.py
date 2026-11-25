from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from django.utils import timezone

from .access import get_role_group, TEACHER_GROUP
from .importers import record_attendance_rate
from .models import (
    Assessment,
    AttendanceRecord,
    Classroom,
    Intervention,
    Student,
    StudentPromotion,
    TeacherAssignment,
)


class StudentEntryForm(forms.ModelForm):
    classroom_name = forms.CharField(
        label='Classroom',
        max_length=100,
        required=False,
        help_text='Enter a classroom name to create it if it does not exist.',
    )
    attendance_rate = forms.FloatField(
        label='Attendance rate (%)',
        min_value=0,
        max_value=100,
        required=False,
        help_text='Optional; enter a percentage from 0 to 100.',
    )
    test_1 = forms.FloatField(label='Test 1 score', min_value=0, max_value=100, required=False)
    assignment_1 = forms.FloatField(
        label='Assignment 1 score', min_value=0, max_value=100, required=False
    )
    project_1 = forms.FloatField(
        label='Project 1 score', min_value=0, max_value=100, required=False
    )
    midterm = forms.FloatField(label='Midterm score', min_value=0, max_value=100, required=False)
    endterm = forms.FloatField(label='End-of-term score', min_value=0, max_value=100, required=False)
    assessment_date = forms.DateField(
        label='Assessment date',
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    subject = forms.ChoiceField(label='Subject', required=False)

    class Meta:
        model = Student
        fields = [
            'student_id',
            'first_name',
            'last_name',
            'gender',
            'date_of_birth',
            'guardian_name',
            'guardian_phone',
        ]
        widgets = {
            'date_of_birth': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        allowed_classrooms = kwargs.pop('allowed_classrooms', None)
        allowed_assignments = kwargs.pop('allowed_assignments', None)
        super().__init__(*args, **kwargs)
        self.allowed_assignments = (
            {(classroom_id, subject) for classroom_id, subject in allowed_assignments}
            if allowed_assignments is not None
            else None
        )
        if allowed_classrooms is not None:
            self.fields['classroom_name'] = forms.ModelChoiceField(
                queryset=allowed_classrooms,
                label='Classroom',
                required=True,
                help_text='Choose one of your assigned classrooms.',
            )
        subjects = sorted({subject for _, subject in self.allowed_assignments or []})
        self.fields['subject'].choices = [('', '---------')] + [
            (subject, subject) for subject in subjects
        ]
        self.order_fields(
            [
                'student_id',
                'first_name',
                'last_name',
                'classroom_name',
                'subject',
                'gender',
                'date_of_birth',
                'guardian_name',
                'guardian_phone',
                'attendance_rate',
                'assessment_date',
                'test_1',
                'assignment_1',
                'project_1',
                'midterm',
                'endterm',
            ]
        )
        self.fields['assessment_date'].initial = timezone.localdate
        if len(subjects) == 1:
            self.fields['subject'].initial = subjects[0]

    def clean(self):
        cleaned_data = super().clean()
        score_fields = ('test_1', 'assignment_1', 'project_1', 'midterm', 'endterm')
        has_score = any(cleaned_data.get(name) is not None for name in score_fields)
        classroom = cleaned_data.get('classroom_name')
        subject = cleaned_data.get('subject')
        if has_score and not subject:
            self.add_error('subject', 'Select a subject for the entered scores.')
        elif (
            has_score
            and classroom
            and self.allowed_assignments is not None
            and (classroom.pk, subject) not in self.allowed_assignments
        ):
            self.add_error('subject', 'You are not assigned to teach this subject in that class.')
        return cleaned_data

    @property
    def has_performance_data(self):
        return self.cleaned_data.get('attendance_rate') is not None or any(
            self.cleaned_data.get(field_name) is not None
            for field_name in ('test_1', 'assignment_1', 'project_1', 'midterm', 'endterm')
        )

    @transaction.atomic
    def save(self, commit=True):
        student = super().save(commit=False)
        classroom_value = self.cleaned_data['classroom_name']
        if isinstance(classroom_value, Classroom):
            student.classroom = classroom_value
        elif classroom_value.strip():
            student.classroom, _ = Classroom.objects.get_or_create(name=classroom_value.strip())
        else:
            student.classroom = None

        if commit:
            student.save()
            self.save_m2m()
            assessment_date = self.cleaned_data.get('assessment_date') or timezone.localdate()
            score_fields = (
                ('test_1', Assessment.AssessmentType.TEST, 'Test 1'),
                ('assignment_1', Assessment.AssessmentType.ASSIGNMENT, 'Assignment 1'),
                ('project_1', Assessment.AssessmentType.PROJECT, 'Project 1'),
                ('midterm', Assessment.AssessmentType.MIDTERM, 'Midterm'),
                ('endterm', Assessment.AssessmentType.ENDTERM, 'End of Term'),
            )
            for field_name, assessment_type, title in score_fields:
                score = self.cleaned_data.get(field_name)
                if score is not None:
                    Assessment.objects.create(
                        student=student,
                        subject=self.cleaned_data.get('subject') or '',
                        assessment_type=assessment_type,
                        title=title,
                        score=score,
                        date=assessment_date,
                    )

            attendance_rate = self.cleaned_data.get('attendance_rate')
            if attendance_rate is not None:
                record_attendance_rate(student, attendance_rate, assessment_date)
        return student


class AssessmentEntryForm(forms.ModelForm):
    class Meta:
        model = Assessment
        fields = ['subject', 'assessment_type', 'title', 'score', 'max_score', 'date', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'score': forms.NumberInput(attrs={'min': '0', 'max': '100', 'step': '0.1'}),
            'max_score': forms.NumberInput(attrs={'min': '1', 'step': '0.1'}),
        }

    def __init__(self, *args, allowed_subjects=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['date'].initial = timezone.localdate
        if allowed_subjects is not None:
            choices = [(subject, subject) for subject in sorted(set(allowed_subjects))]
            self.fields['subject'] = forms.ChoiceField(
                choices=choices,
                required=True,
                label='Subject',
            )

    def clean(self):
        cleaned_data = super().clean()
        score = cleaned_data.get('score')
        max_score = cleaned_data.get('max_score')
        if score is not None and max_score is not None and score > max_score:
            self.add_error('score', 'Score cannot exceed the maximum score.')
        return cleaned_data


class AttendanceEntryForm(forms.ModelForm):
    class Meta:
        model = AttendanceRecord
        fields = ['date', 'status', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.TextInput(attrs={'maxlength': 255}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['date'].initial = timezone.localdate


class StudentProfileForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = [
            'student_id',
            'first_name',
            'last_name',
            'gender',
            'classroom',
            'date_of_birth',
            'guardian_name',
            'guardian_phone',
            'is_active',
        ]
        widgets = {
            'date_of_birth': forms.DateInput(attrs={'type': 'date'}),
        }


class PromotionForm(forms.ModelForm):
    class Meta:
        model = StudentPromotion
        fields = ['to_classroom', 'promoted_at', 'notes']
        widgets = {
            'promoted_at': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, current_classroom=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_classroom = current_classroom
        self.fields['promoted_at'].initial = timezone.localdate

    def clean_to_classroom(self):
        destination = self.cleaned_data['to_classroom']
        if destination == self.current_classroom:
            raise forms.ValidationError('Select a different classroom to promote the student.')
        return destination


class TeacherAccountForm(UserCreationForm):
    email = forms.EmailField(required=False)
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    classrooms = forms.ModelMultipleChoiceField(
        queryset=Classroom.objects.all(),
        widget=forms.CheckboxSelectMultiple,
    )
    subject = forms.CharField(max_length=100)

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ('username', 'first_name', 'last_name', 'email')

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            user.groups.add(get_role_group(TEACHER_GROUP))
            for classroom in self.cleaned_data['classrooms']:
                TeacherAssignment.objects.create(
                    teacher=user,
                    classroom=classroom,
                    subject=self.cleaned_data['subject'].strip(),
                )
        return user


class TeacherAssignmentForm(forms.Form):
    classrooms = forms.ModelMultipleChoiceField(
        queryset=Classroom.objects.all(),
        widget=forms.CheckboxSelectMultiple,
    )
    subject = forms.CharField(max_length=100)

    @transaction.atomic
    def save(self, teacher):
        subject = self.cleaned_data['subject'].strip()
        classrooms = self.cleaned_data['classrooms']
        TeacherAssignment.objects.filter(teacher=teacher, subject=subject).exclude(
            classroom__in=classrooms
        ).delete()
        for classroom in classrooms:
            TeacherAssignment.objects.get_or_create(
                teacher=teacher,
                classroom=classroom,
                subject=subject,
            )


class ClassroomInterventionForm(forms.Form):
    action = forms.ChoiceField(choices=Intervention.Action.choices)
    reason = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}))
