from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from students.access import assigned_students, is_school_administrator
from students.models import Student
from students.permissions import IsSchoolAdministrator
from students.serializers import AlertSerializer, InterventionSerializer, RiskPredictionSerializer

from .ml_engine import risk_model
from .risk_service import (
    dashboard_summary,
    predict_student,
    risk_report_rows,
    run_batch_predictions,
)


@api_view(['GET'])
def summary(request):
    students = None if is_school_administrator(request.user) else assigned_students(request.user)
    return Response(dashboard_summary(students=students))


@api_view(['GET'])
def risk_report(request):
    students = None if is_school_administrator(request.user) else assigned_students(request.user)
    return Response(risk_report_rows(students=students))


@api_view(['POST'])
@permission_classes([IsSchoolAdministrator])
def train_model(request):
    metrics = risk_model.train()
    return Response(metrics)


@api_view(['POST'])
def run_predictions(request):
    retrain = str(request.data.get('retrain', 'false')).lower() in ('1', 'true', 'yes')
    admin = is_school_administrator(request.user)
    if retrain and not admin:
        return Response(
            {'detail': 'Only a School Administrator can retrain the school-wide model.'},
            status=status.HTTP_403_FORBIDDEN,
        )
    students = None if admin else assigned_students(request.user)
    result = run_batch_predictions(retrain=retrain, students=students)
    return Response(result)


@api_view(['POST'])
def predict_one(request, student_id: int):
    try:
        students = (
            Student.objects.all()
            if is_school_administrator(request.user)
            else assigned_students(request.user)
        )
        student = students.get(pk=student_id)
    except Student.DoesNotExist:
        return Response({'detail': 'Student not found.'}, status=status.HTTP_404_NOT_FOUND)
    prediction = predict_student(student)
    return Response(
        {
            'prediction': (
                RiskPredictionSerializer(prediction).data if prediction else None
            ),
            'alerts': AlertSerializer(student.alerts.filter(is_acknowledged=False)[:10], many=True).data,
            'interventions': InterventionSerializer(
                student.interventions.filter(is_completed=False), many=True
            ).data,
        }
    )


@api_view(['GET'])
@permission_classes([IsSchoolAdministrator])
def model_status(request):
    loaded = risk_model.pipeline is not None or risk_model.load()
    return Response(
        {
            'model_loaded': bool(loaded),
            'model_path': str(risk_model.model_path),
            'metrics': risk_model.metrics,
        }
    )


@api_view(['GET'])
def chart_data(request):
    """Payload for Chart.js / Plotly dashboards."""
    students = None if is_school_administrator(request.user) else assigned_students(request.user)
    rows = risk_report_rows(students=students)
    risk_counts = {'low': 0, 'medium': 0, 'high': 0, 'unassessed': 0}
    for row in rows:
        risk_counts[row['risk_level']] = risk_counts.get(row['risk_level'], 0) + 1

    top_risk = [r for r in rows if r['failure_risk'] is not None][:10]
    return Response(
        {
            'summary': dashboard_summary(students=students),
            'risk_distribution': risk_counts,
            'top_risk_students': {
                'labels': [r['name'] for r in top_risk],
                'probabilities': [round(r['failure_risk'] or 0, 1) for r in top_risk],
                'averages': [round(r['average'] or 0, 1) for r in top_risk],
            },
            'attendance_vs_risk': [
                {
                    'name': r['name'],
                    'attendance': round(r['attendance'] or 0, 1),
                    'risk': round(r['failure_risk'] or 0, 1),
                    'average': round(r['average'] or 0, 1),
                }
                for r in rows
                if r['failure_risk'] is not None
            ],
        }
    )
