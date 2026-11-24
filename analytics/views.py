from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from students.models import Student
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
    return Response(dashboard_summary())


@api_view(['GET'])
def risk_report(request):
    return Response(risk_report_rows())


@api_view(['POST'])
def train_model(request):
    metrics = risk_model.train()
    return Response(metrics)


@api_view(['POST'])
def run_predictions(request):
    retrain = str(request.data.get('retrain', 'false')).lower() in ('1', 'true', 'yes')
    result = run_batch_predictions(retrain=retrain)
    return Response(result)


@api_view(['POST'])
def predict_one(request, student_id: int):
    try:
        student = Student.objects.get(pk=student_id)
    except Student.DoesNotExist:
        return Response({'detail': 'Student not found.'}, status=status.HTTP_404_NOT_FOUND)
    prediction = predict_student(student)
    return Response(
        {
            'prediction': RiskPredictionSerializer(prediction).data,
            'alerts': AlertSerializer(student.alerts.filter(is_acknowledged=False)[:10], many=True).data,
            'interventions': InterventionSerializer(
                student.interventions.filter(is_completed=False), many=True
            ).data,
        }
    )


@api_view(['GET'])
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
    rows = risk_report_rows()
    risk_counts = {'low': 0, 'medium': 0, 'high': 0, 'unassessed': 0}
    for row in rows:
        risk_counts[row['risk_level']] = risk_counts.get(row['risk_level'], 0) + 1

    top_risk = [r for r in rows if r['failure_risk'] is not None][:10]
    return Response(
        {
            'summary': dashboard_summary(),
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
