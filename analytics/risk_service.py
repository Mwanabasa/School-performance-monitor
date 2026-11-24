"""Risk analysis, alerts, and intervention recommendations."""
from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from students.models import Alert, Intervention, RiskPrediction, Student

from .features import compute_student_features
from .ml_engine import risk_model


def classify_risk(probability: float) -> str:
    if probability >= settings.RISK_THRESHOLD_HIGH:
        return RiskPrediction.RiskLevel.HIGH
    if probability >= settings.RISK_THRESHOLD_MEDIUM:
        return RiskPrediction.RiskLevel.MEDIUM
    return RiskPrediction.RiskLevel.LOW


def recommend_actions(features: dict, risk_level: str) -> list[tuple[str, str]]:
    actions: list[tuple[str, str]] = []
    avg = features.get('avg_score', 0)
    attendance = features.get('attendance_rate', 1)
    declining = bool(features.get('is_declining'))
    midterm = features.get('midterm_score', avg)

    if risk_level == RiskPrediction.RiskLevel.HIGH or avg < 45:
        actions.append(
            (
                Intervention.Action.REMEDIAL,
                'Low performance indicators suggest scheduled remedial lessons.',
            )
        )
        actions.append(
            (
                Intervention.Action.CONSULTATION,
                'Schedule an individual consultation to identify learning barriers.',
            )
        )
    if declining:
        actions.append(
            (
                Intervention.Action.EXTRA_ASSIGNMENT,
                'Scores are declining across assessments — assign targeted practice work.',
            )
        )
    if attendance < 0.75:
        actions.append(
            (
                Intervention.Action.ATTENDANCE_FOLLOWUP,
                f'Attendance rate is {attendance:.0%}. Follow up on absences.',
            )
        )
    if risk_level != RiskPrediction.RiskLevel.LOW and midterm < 50:
        actions.append(
            (
                Intervention.Action.PEER_TUTORING,
                'Midterm performance is weak — peer tutoring may help before end-of-term.',
            )
        )
    if risk_level == RiskPrediction.RiskLevel.HIGH:
        actions.append(
            (
                Intervention.Action.GUARDIAN_MEETING,
                'High failure risk — involve the guardian in an intervention plan.',
            )
        )

    # Deduplicate by action type, keep first reason
    seen = set()
    unique = []
    for action, reason in actions:
        if action not in seen:
            seen.add(action)
            unique.append((action, reason))
    return unique


def _create_alerts(student: Student, prediction: RiskPrediction, features: dict) -> list[Alert]:
    alerts = []
    if prediction.risk_level == RiskPrediction.RiskLevel.HIGH:
        alerts.append(
            Alert(
                student=student,
                alert_type=Alert.AlertType.HIGH_RISK,
                severity=RiskPrediction.RiskLevel.HIGH,
                message=(
                    f'{student.full_name} has a high estimated failure risk '
                    f'({prediction.failure_probability:.0%}). Review interventions.'
                ),
            )
        )
    elif prediction.risk_level == RiskPrediction.RiskLevel.MEDIUM:
        alerts.append(
            Alert(
                student=student,
                alert_type=Alert.AlertType.THRESHOLD,
                severity=RiskPrediction.RiskLevel.MEDIUM,
                message=(
                    f'{student.full_name} crossed the medium risk threshold '
                    f'({prediction.failure_probability:.0%}).'
                ),
            )
        )

    if prediction.is_declining:
        alerts.append(
            Alert(
                student=student,
                alert_type=Alert.AlertType.DECLINE,
                severity=prediction.risk_level,
                message=(
                    f'{student.full_name} shows a declining performance trend '
                    f'(slope {prediction.trend_slope:.2f} points per assessment).'
                ),
            )
        )

    attendance = features.get('attendance_rate', 1.0)
    if attendance < 0.7:
        alerts.append(
            Alert(
                student=student,
                alert_type=Alert.AlertType.ATTENDANCE,
                severity=(
                    RiskPrediction.RiskLevel.HIGH
                    if attendance < 0.55
                    else RiskPrediction.RiskLevel.MEDIUM
                ),
                message=(
                    f'{student.full_name} attendance is low ({attendance:.0%}).'
                ),
            )
        )

    Alert.objects.bulk_create(alerts)
    return alerts


@transaction.atomic
def predict_student(student: Student, create_alerts: bool = True, create_interventions: bool = True) -> RiskPrediction:
    features = compute_student_features(student)
    probability = risk_model.predict_proba(features)
    risk_level = classify_risk(probability)

    prediction = RiskPrediction.objects.create(
        student=student,
        failure_probability=probability,
        risk_level=risk_level,
        average_score=features.get('avg_score'),
        attendance_rate=features.get('attendance_rate'),
        trend_slope=features.get('trend_slope'),
        is_declining=bool(features.get('is_declining')),
        features_snapshot=features,
        model_version=risk_model.metrics.get('best_model', 'heuristic'),
    )

    if create_alerts:
        # Clear unacknowledged duplicate-type alerts from today to avoid spam
        Alert.objects.filter(
            student=student,
            is_acknowledged=False,
            created_at__date=timezone.localdate(),
        ).delete()
        _create_alerts(student, prediction, features)

    if create_interventions:
        Intervention.objects.filter(
            student=student,
            suggested_by_system=True,
            is_completed=False,
        ).delete()
        for action, reason in recommend_actions(features, risk_level):
            Intervention.objects.create(
                student=student,
                action=action,
                reason=reason,
                suggested_by_system=True,
            )

    return prediction


def run_batch_predictions(retrain: bool = False) -> dict:
    if retrain or not risk_model.model_path.exists():
        train_metrics = risk_model.train()
    else:
        risk_model.load()
        train_metrics = risk_model.metrics or {'status': 'loaded'}

    students = Student.objects.filter(is_active=True)
    predictions = []
    for student in students:
        predictions.append(predict_student(student))

    summary = {
        'trained': train_metrics,
        'students_scored': len(predictions),
        'high_risk': sum(1 for p in predictions if p.risk_level == RiskPrediction.RiskLevel.HIGH),
        'medium_risk': sum(1 for p in predictions if p.risk_level == RiskPrediction.RiskLevel.MEDIUM),
        'low_risk': sum(1 for p in predictions if p.risk_level == RiskPrediction.RiskLevel.LOW),
        'declining': sum(1 for p in predictions if p.is_declining),
    }
    return summary


def dashboard_summary() -> dict:
    students = Student.objects.filter(is_active=True)
    total = students.count()
    latest_ids = []
    high = medium = low = declining = unassessed = 0

    for student in students:
        latest = student.risk_predictions.first()
        if not latest:
            unassessed += 1
            continue
        latest_ids.append(latest.id)
        if latest.risk_level == RiskPrediction.RiskLevel.HIGH:
            high += 1
        elif latest.risk_level == RiskPrediction.RiskLevel.MEDIUM:
            medium += 1
        else:
            low += 1
        if latest.is_declining:
            declining += 1

    open_alerts = Alert.objects.filter(is_acknowledged=False).count()
    return {
        'total_learners': total,
        'on_track': low,
        'need_attention': medium,
        'high_risk': high,
        'declining': declining,
        'unassessed': unassessed,
        'open_alerts': open_alerts,
    }


def risk_report_rows() -> list[dict]:
    rows = []
    for student in Student.objects.filter(is_active=True).select_related('classroom'):
        latest = student.risk_predictions.first()
        rows.append(
            {
                'id': student.id,
                'student_id': student.student_id,
                'name': student.full_name,
                'classroom': student.classroom.name if student.classroom else '',
                'average': latest.average_score if latest else None,
                'attendance': (latest.attendance_rate * 100) if latest and latest.attendance_rate is not None else None,
                'failure_risk': (latest.failure_probability * 100) if latest else None,
                'risk_level': latest.risk_level if latest else 'unassessed',
                'is_declining': latest.is_declining if latest else False,
                'trend_slope': latest.trend_slope if latest else None,
            }
        )
    rows.sort(key=lambda r: (-(r['failure_risk'] or 0), r['name']))
    return rows
