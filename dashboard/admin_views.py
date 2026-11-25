from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.shortcuts import get_object_or_404, redirect, render

from analytics.risk_service import classroom_performance_rows, dashboard_summary
from students.access import TEACHER_GROUP, school_admin_required
from students.forms import (
    PromotionForm,
    ClassroomInterventionForm,
    StudentProfileForm,
    TeacherAccountForm,
    TeacherAssignmentForm,
)
from students.models import Alert, Classroom, Intervention, RiskPrediction, Student, TeacherActivity


@login_required
@school_admin_required
def home(request):
    User = get_user_model()
    teachers = (
        User.objects.filter(groups__name=TEACHER_GROUP)
        .distinct()
        .prefetch_related('class_assignments__classroom')
    )
    classroom_rows = classroom_performance_rows()
    ranked_classes = [row for row in classroom_rows if row['average_score'] is not None]
    best_class = max(ranked_classes, key=lambda row: row['average_score'], default=None)
    lowest_class = min(ranked_classes, key=lambda row: row['average_score'], default=None)
    return render(
        request,
        'school_admin/home.html',
        {
            'summary': dashboard_summary(),
            'student_count': Student.objects.filter(is_active=True).count(),
            'classroom_count': Classroom.objects.count(),
            'teacher_count': teachers.count(),
            'teachers': teachers,
            'activities': TeacherActivity.objects.select_related(
                'teacher', 'student', 'classroom'
            )[:30],
            'open_alerts': Alert.objects.filter(is_acknowledged=False).count(),
            'classroom_rows': classroom_rows,
            'best_class': best_class,
            'lowest_class': lowest_class,
            'school_name': 'Bethel Parents SS',
        },
    )


@login_required
@school_admin_required
def students(request):
    return render(
        request,
        'school_admin/students.html',
        {
            'students': Student.objects.select_related('classroom').all(),
            'school_name': 'Bethel Parents SS',
        },
    )


@login_required
@school_admin_required
def student_form(request, student_id=None):
    student = get_object_or_404(Student, pk=student_id) if student_id else None
    form = StudentProfileForm(request.POST or None, instance=student)
    if request.method == 'POST' and form.is_valid():
        saved_student = form.save()
        messages.success(
            request,
            f'Saved student record for {saved_student.full_name}.',
        )
        return redirect('school-admin-students')
    return render(
        request,
        'school_admin/student_form.html',
        {
            'form': form,
            'student': student,
            'school_name': 'Bethel Parents SS',
        },
    )


@login_required
@school_admin_required
def promote_student(request, student_id):
    student = get_object_or_404(Student.objects.select_related('classroom'), pk=student_id)
    form = PromotionForm(
        request.POST or None,
        current_classroom=student.classroom,
    )
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            promotion = form.save(commit=False)
            promotion.student = student
            promotion.from_classroom = student.classroom
            promotion.promoted_by = request.user
            promotion.academic_year = promotion.to_classroom.academic_year
            promotion.save()
            student.classroom = promotion.to_classroom
            student.save(update_fields=['classroom', 'updated_at'])
        messages.success(request, f'{student.full_name} was promoted to {student.classroom}.')
        return redirect('school-admin-students')
    return render(
        request,
        'school_admin/promotion_form.html',
        {
            'form': form,
            'student': student,
            'school_name': 'Bethel Parents SS',
        },
    )


@login_required
@school_admin_required
def teachers(request):
    User = get_user_model()
    teacher_accounts = (
        User.objects.filter(groups__name=TEACHER_GROUP)
        .distinct()
        .prefetch_related('class_assignments__classroom')
        .order_by('last_name', 'first_name', 'username')
    )
    return render(
        request,
        'school_admin/teachers.html',
        {
            'teachers': teacher_accounts,
            'school_name': 'Bethel Parents SS',
        },
    )


@login_required
@school_admin_required
def teacher_form(request):
    form = TeacherAccountForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        teacher = form.save()
        messages.success(request, f'Created teacher account for {teacher.get_username()}.')
        return redirect('school-admin-teachers')
    return render(
        request,
        'school_admin/teacher_form.html',
        {
            'form': form,
            'school_name': 'Bethel Parents SS',
        },
    )


@login_required
@school_admin_required
def teacher_assign(request, teacher_id):
    User = get_user_model()
    teacher = get_object_or_404(
        User.objects.filter(groups__name=TEACHER_GROUP).distinct(),
        pk=teacher_id,
    )
    existing_assignments = teacher.class_assignments.select_related('classroom')
    existing_subject = existing_assignments.values_list('subject', flat=True).first() or ''
    initial_classrooms = list(
        existing_assignments.filter(subject=existing_subject).values_list('classroom_id', flat=True)
    )
    form = TeacherAssignmentForm(
        request.POST or None,
        initial={'subject': existing_subject, 'classrooms': initial_classrooms},
    )
    if request.method == 'POST' and form.is_valid():
        form.save(teacher)
        messages.success(request, f'Updated classroom assignments for {teacher.get_username()}.')
        return redirect('school-admin-teachers')
    return render(
        request,
        'school_admin/teacher_assign.html',
        {
            'form': form,
            'teacher': teacher,
            'assignments': existing_assignments,
            'school_name': 'Bethel Parents SS',
        },
    )


@login_required
@school_admin_required
def plan_class_intervention(request, classroom_id):
    classroom = get_object_or_404(Classroom, pk=classroom_id)
    latest_prediction = RiskPrediction.objects.filter(
        student_id=OuterRef('pk')
    ).order_by('-predicted_at', '-id')
    high_risk_students = Student.objects.filter(
        classroom=classroom,
        is_active=True,
    ).annotate(
        latest_risk=Subquery(latest_prediction.values('risk_level')[:1])
    ).filter(latest_risk=RiskPrediction.RiskLevel.HIGH)
    form = ClassroomInterventionForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        count = high_risk_students.count()
        if not count:
            form.add_error(None, 'There are no currently high-risk students in this class.')
        else:
            action = form.cleaned_data['action']
            reason = (
                f"School intervention for {classroom.name}: "
                f"{form.cleaned_data['reason'].strip()}"
            )
            Intervention.objects.bulk_create(
                [
                    Intervention(
                        student=student,
                        action=action,
                        reason=reason,
                        suggested_by_system=False,
                    )
                    for student in high_risk_students
                ]
            )
            messages.success(
                request,
                f'Created {count} intervention records for high-risk students in {classroom.name}.',
            )
            return redirect('school-admin-home')
    return render(
        request,
        'school_admin/intervention_form.html',
        {
            'form': form,
            'classroom': classroom,
            'high_risk_count': high_risk_students.count(),
            'school_name': 'Bethel Parents SS',
        },
    )
