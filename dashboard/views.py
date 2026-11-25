import json
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_http_methods

from analytics.risk_service import (
    classroom_performance_rows,
    dashboard_summary,
    predict_student,
    risk_report_rows,
    run_batch_predictions,
)
from students.access import (
    assigned_classrooms,
    assigned_students,
    is_school_administrator,
    is_teacher,
    record_teacher_activity,
    school_user_required,
    teacher_assignments,
)
from students.forms import (
    AssessmentEntryForm,
    AttendanceEntryForm,
    StudentEntryForm,
)
from students.models import Alert, Assessment, AttendanceRecord, Intervention, Student

from .reporting import build_performance_workbook


@login_required
def role_dashboard(request):
    if is_school_administrator(request.user):
        return redirect('school-admin-home')
    if is_teacher(request.user):
        return redirect('dashboard-home')
    return HttpResponseForbidden('Your account has no school dashboard role.')


@school_user_required
def home(request):
    if is_school_administrator(request.user):
        return redirect('school-admin-home')
    students = assigned_students(request.user)
    summary = dashboard_summary(students=students)
    visible_assessments = Assessment.objects.filter(
        student__classroom__teacher_assignments__teacher=request.user,
        subject=F('student__classroom__teacher_assignments__subject'),
    ).distinct()
    report = risk_report_rows(
        students=students,
        assessment_queryset=visible_assessments,
    )
    class_rows = {
        row['id']: row
        for row in classroom_performance_rows(
            students=students,
            assessment_queryset=visible_assessments,
        )
    }
    my_classes = []
    for assignment in teacher_assignments(request.user):
        class_row = class_rows.get(assignment.classroom_id)
        if class_row:
            my_classes.append({**class_row, 'subject': assignment.subject})
    alerts = Alert.objects.filter(
        student__in=students,
        is_acknowledged=False,
    ).select_related('student')[:15]
    return render(
        request,
        'dashboard/home.html',
        {
            'summary': summary,
            'report': report,
            'alerts': alerts,
            'my_classes': my_classes,
            'classrooms': assigned_classrooms(request.user),
            'school_name': 'Bethel Parents SS',
        },
    )


@school_user_required
def student_detail(request, student_id: int):
    student_queryset = (
        Student.objects.select_related('classroom').prefetch_related(
            'assessments', 'attendance_records', 'risk_predictions', 'alerts', 'interventions'
        )
    )
    if not is_school_administrator(request.user):
        student_queryset = student_queryset.filter(
            classroom__teacher_assignments__teacher=request.user
        ).distinct()
    student = get_object_or_404(student_queryset, pk=student_id)
    subject_options = None
    if is_teacher(request.user):
        subject_options = list(
            teacher_assignments(request.user)
            .filter(classroom=student.classroom)
            .values_list('subject', flat=True)
        )
    assessment_form = (
        AssessmentEntryForm(allowed_subjects=subject_options)
        if subject_options is not None
        else None
    )
    attendance_form = AttendanceEntryForm() if is_teacher(request.user) else None
    if request.method == 'POST' and 'add_attendance' in request.POST:
        if not is_teacher(request.user):
            return HttpResponseForbidden('Only assigned teachers can record attendance.')
        attendance_form = AttendanceEntryForm(request.POST)
        if attendance_form.is_valid():
            attendance, created = AttendanceRecord.objects.update_or_create(
                student=student,
                date=attendance_form.cleaned_data['date'],
                defaults={
                    'status': attendance_form.cleaned_data['status'],
                    'notes': attendance_form.cleaned_data['notes'],
                },
            )
            record_teacher_activity(
                request.user,
                'attendance_recorded',
                f'{attendance.date}: {attendance.get_status_display()}.',
                student=student,
            )
            predict_student(student)
            verb = 'Recorded' if created else 'Updated'
            messages.success(request, f'{verb} attendance for {student.full_name}.')
            return redirect('dashboard-student', student_id=student.id)
    if request.method == 'POST' and 'add_assessment' in request.POST:
        if not is_teacher(request.user):
            return HttpResponseForbidden('Only assigned teachers can record assessments.')
        assessment_form = AssessmentEntryForm(
            request.POST,
            allowed_subjects=subject_options,
        )
        if assessment_form.is_valid():
            assessment = assessment_form.save(commit=False)
            assessment.student = student
            assessment.save()
            record_teacher_activity(
                request.user,
                'assessment_recorded',
                f'{assessment.subject} — {assessment.get_assessment_type_display()}: '
                f'{assessment.title} ({assessment.percentage:.1f}%).',
                student=student,
            )
            if assessment.assessment_type == Assessment.AssessmentType.ENDTERM:
                run_batch_predictions(students=assigned_students(request.user))
            else:
                predict_student(student)
            messages.success(
                request,
                f'Saved {assessment.get_assessment_type_display()} for {student.full_name}.',
            )
            return redirect('dashboard-student', student_id=student.id)

    latest = student.risk_predictions.first()
    assessment_queryset = student.assessments.order_by('date')
    if subject_options is not None:
        assessment_queryset = assessment_queryset.filter(subject__in=subject_options)
    assessments = list(assessment_queryset)
    chart_labels = [a.date.isoformat() for a in assessments]
    chart_scores = [a.percentage for a in assessments]
    attendance_pct = None
    failure_pct = None
    if latest:
        if latest.attendance_rate is not None:
            attendance_pct = latest.attendance_rate * 100
        failure_pct = latest.failure_probability * 100
    return render(
        request,
        'dashboard/student_detail.html',
        {
            'student': student,
            'assessment_form': assessment_form,
            'attendance_form': attendance_form,
            'latest': latest,
            'assessments': assessments,
            'attendance_records': student.attendance_records.order_by('-date')[:30],
            'alerts': student.alerts.all()[:20],
            'interventions': student.interventions.all()[:20],
            'chart_labels_json': json.dumps(chart_labels),
            'chart_scores_json': json.dumps(chart_scores),
            'attendance_pct': attendance_pct,
            'failure_pct': failure_pct,
            'promotions': (
                student.promotions.select_related('from_classroom', 'to_classroom', 'promoted_by')
                if is_school_administrator(request.user)
                else []
            ),
            'school_name': 'Bethel Parents SS',
        },
    )


@school_user_required
@require_http_methods(['POST'])
def run_analysis(request):
    retrain = request.POST.get('retrain') == 'on'
    if retrain and not is_school_administrator(request.user):
        messages.error(request, 'Only a School Administrator can retrain the school-wide model.')
        retrain = False
    students = None if is_school_administrator(request.user) else assigned_students(request.user)
    run_batch_predictions(retrain=retrain, students=students)
    return redirect('role-dashboard')


@school_user_required
@require_http_methods(['POST'])
def acknowledge_alert(request, alert_id: int):
    alerts = Alert.objects.all()
    if not is_school_administrator(request.user):
        alerts = alerts.filter(student__in=assigned_students(request.user))
    alert = get_object_or_404(alerts, pk=alert_id)
    alert.is_acknowledged = True
    alert.acknowledged_at = timezone.now()
    alert.save(update_fields=['is_acknowledged', 'acknowledged_at'])
    next_url = request.POST.get('next') or 'dashboard-home'
    if next_url.startswith('/'):
        return redirect(next_url)
    return redirect('dashboard-home')


@school_user_required
@require_http_methods(['POST'])
def complete_intervention(request, student_id: int, intervention_id: int):
    if not is_teacher(request.user):
        return HttpResponseForbidden('Only assigned teachers can complete interventions.')
    student = get_object_or_404(assigned_students(request.user), pk=student_id)
    intervention = get_object_or_404(
        Intervention,
        pk=intervention_id,
        student=student,
    )
    intervention.is_completed = True
    intervention.completed_at = timezone.now()
    notes = request.POST.get('notes', '').strip()
    if notes:
        intervention.notes = notes
    intervention.save(update_fields=['is_completed', 'completed_at', 'notes'])
    messages.success(request, f'Marked intervention complete for {student.full_name}.')
    return redirect('dashboard-student', student_id=student.id)


@school_user_required
def import_page(request):
    if is_school_administrator(request.user):
        return redirect('school-admin-students')
    message = None
    error = None
    classrooms = assigned_classrooms(request.user)
    assignments = list(teacher_assignments(request.user))
    allowed_assignments = [
        (assignment.classroom_id, assignment.subject) for assignment in assignments
    ]

    def entry_form(data=None):
        return StudentEntryForm(
            data,
            allowed_classrooms=classrooms,
            allowed_assignments=allowed_assignments,
        )

    form = entry_form()
    if request.method == 'POST':
        if 'add_student' in request.POST:
            form = entry_form(request.POST)
            if form.is_valid():
                has_performance_data = form.has_performance_data
                includes_endterm = form.cleaned_data.get('endterm') is not None
                entered_scores = [
                    f'{form.cleaned_data.get("subject")}: '
                    f'{field.replace("_", " ").title()}: {form.cleaned_data[field]}'
                    for field in ('test_1', 'assignment_1', 'project_1', 'midterm', 'endterm')
                    if form.cleaned_data.get(field) is not None
                ]
                attendance_rate = form.cleaned_data.get('attendance_rate')
                student = form.save()
                record_teacher_activity(
                    request.user,
                    'student_registered',
                    'Student record added through the dashboard.',
                    student=student,
                )
                if entered_scores:
                    record_teacher_activity(
                        request.user,
                        'assessment_recorded',
                        ', '.join(entered_scores),
                        student=student,
                    )
                if attendance_rate is not None:
                    record_teacher_activity(
                        request.user,
                        'attendance_recorded',
                        f'Attendance rate recorded: {attendance_rate:.0f}%.',
                        student=student,
                    )
                if has_performance_data:
                    if includes_endterm:
                        run_batch_predictions(students=assigned_students(request.user))
                    else:
                        predict_student(student)
                messages.success(request, f'Added {student.full_name} ({student.student_id}).')
                return redirect('dashboard-import')
        elif request.FILES.get('file'):
            from students.importers import import_students_from_excel

            try:
                allowed_subjects = {}
                for assignment in assignments:
                    allowed_subjects.setdefault(assignment.classroom_id, set()).add(
                        assignment.subject
                    )
                result = import_students_from_excel(
                    request.FILES['file'],
                    allowed_classrooms=classrooms,
                    allowed_subjects=allowed_subjects,
                )
                message = (
                    f"Imported {result['rows_processed']} rows — "
                    f"{result['students_created']} created, {result['students_updated']} updated, "
                    f"{result['assessments_created']} assessments."
                )
                record_teacher_activity(
                    request.user,
                    'student_import',
                    f"Imported {result['rows_processed']} rows; "
                    f"{result['students_created']} created and "
                    f"{result['students_updated']} updated.",
                )
                run_batch_predictions(students=assigned_students(request.user))
            except ValueError as exc:
                error = str(exc)
    return render(
        request,
        'dashboard/import.html',
        {
            'message': message,
            'error': error,
            'form': form,
            'classrooms': classrooms,
            'school_name': 'Bethel Parents SS',
        },
    )


@school_user_required
@require_http_methods(['GET'])
def export_performance_report(request):
    students = None if is_school_administrator(request.user) else assigned_students(request.user)
    assessment_queryset = None
    filename = 'student-performance-report.xlsx'
    if is_teacher(request.user):
        classroom_id = request.GET.get('classroom')
        if classroom_id:
            classroom = get_object_or_404(assigned_classrooms(request.user), pk=classroom_id)
            students = students.filter(classroom=classroom)
            filename = f'{slugify(classroom.name) or "class"}-performance-report.xlsx'
        assessment_queryset = Assessment.objects.filter(
            student__in=students,
            student__classroom__teacher_assignments__teacher=request.user,
            subject=F('student__classroom__teacher_assignments__subject'),
        ).distinct()
    workbook = build_performance_workbook(
        students=students,
        assessment_queryset=assessment_queryset,
    )
    output = BytesIO()
    workbook.save(output)
    response = HttpResponse(
        output.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
