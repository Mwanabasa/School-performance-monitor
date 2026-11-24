import json

from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from analytics.risk_service import dashboard_summary, risk_report_rows, run_batch_predictions
from students.models import Alert, Assessment, Intervention, Student


def home(request):
    summary = dashboard_summary()
    report = risk_report_rows()
    alerts = Alert.objects.filter(is_acknowledged=False).select_related('student')[:15]
    return render(
        request,
        'dashboard/home.html',
        {
            'summary': summary,
            'report': report,
            'alerts': alerts,
            'school_name': 'Bethel Parents SS',
        },
    )


def student_detail(request, student_id: int):
    student = get_object_or_404(
        Student.objects.select_related('classroom').prefetch_related(
            'assessments', 'attendance_records', 'risk_predictions', 'alerts', 'interventions'
        ),
        pk=student_id,
    )
    latest = student.risk_predictions.first()
    assessments = list(student.assessments.order_by('date'))
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
            'latest': latest,
            'assessments': assessments,
            'alerts': student.alerts.all()[:20],
            'interventions': student.interventions.all()[:20],
            'chart_labels_json': json.dumps(chart_labels),
            'chart_scores_json': json.dumps(chart_scores),
            'attendance_pct': attendance_pct,
            'failure_pct': failure_pct,
            'school_name': 'Bethel Parents SS',
        },
    )


@require_http_methods(['POST'])
def run_analysis(request):
    retrain = request.POST.get('retrain') == 'on'
    run_batch_predictions(retrain=retrain)
    return redirect('dashboard-home')


@require_http_methods(['POST'])
def acknowledge_alert(request, alert_id: int):
    alert = get_object_or_404(Alert, pk=alert_id)
    from django.utils import timezone

    alert.is_acknowledged = True
    alert.acknowledged_at = timezone.now()
    alert.save(update_fields=['is_acknowledged', 'acknowledged_at'])
    next_url = request.POST.get('next') or 'dashboard-home'
    if next_url.startswith('/'):
        return redirect(next_url)
    return redirect('dashboard-home')


def import_page(request):
    message = None
    error = None
    if request.method == 'POST' and request.FILES.get('file'):
        from students.importers import import_students_from_excel

        try:
            result = import_students_from_excel(request.FILES['file'])
            message = (
                f"Imported {result['rows_processed']} rows — "
                f"{result['students_created']} created, {result['students_updated']} updated, "
                f"{result['assessments_created']} assessments."
            )
        except Exception as exc:
            error = str(exc)
    return render(
        request,
        'dashboard/import.html',
        {'message': message, 'error': error, 'school_name': 'Bethel Parents SS'},
    )
