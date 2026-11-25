"""Risk analysis, alerts, and intervention recommendations."""
from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone

from students.models import (
    Alert,
    Assessment,
    AttendanceRecord,
    AttendanceSnapshot,
    Intervention,
    RiskPrediction,
    Student,
)

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
    if attendance < settings.ATTENDANCE_RISK_THRESHOLD:
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
                    f'{student.full_name} scores have declined across three consecutive '
                    f'assessments (trend slope {prediction.trend_slope:.2f} points per assessment).'
                ),
            )
        )

    attendance = features.get('attendance_rate', 1.0)
    if attendance < settings.ATTENDANCE_RISK_THRESHOLD:
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
def predict_student(
    student: Student,
    create_alerts: bool = True,
    create_interventions: bool = True,
) -> RiskPrediction | None:
    features = compute_student_features(student)
    if features['assessment_count'] == 0:
        if create_alerts:
            Alert.objects.filter(
                student=student,
                is_acknowledged=False,
                created_at__date=timezone.localdate(),
            ).delete()
            attendance = features['attendance_rate']
            if (
                features['has_attendance_data']
                and attendance < settings.ATTENDANCE_RISK_THRESHOLD
            ):
                Alert.objects.create(
                    student=student,
                    alert_type=Alert.AlertType.ATTENDANCE,
                    severity=(
                        RiskPrediction.RiskLevel.HIGH
                        if attendance < 0.55
                        else RiskPrediction.RiskLevel.MEDIUM
                    ),
                    message=f'{student.full_name} attendance is low ({attendance:.0%}).',
                )
        if create_interventions:
            Intervention.objects.filter(
                student=student,
                suggested_by_system=True,
                is_completed=False,
            ).delete()
            if features['has_attendance_data']:
                for action, reason in recommend_actions(
                    features, RiskPrediction.RiskLevel.LOW
                ):
                    if action == Intervention.Action.ATTENDANCE_FOLLOWUP:
                        Intervention.objects.create(
                            student=student,
                            action=action,
                            reason=reason,
                            suggested_by_system=True,
                        )
        return None

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


def run_batch_predictions(retrain: bool = False, students=None) -> dict:
    if retrain:
        train_metrics = risk_model.train()
    else:
        if risk_model.load():
            train_metrics = risk_model.metrics or {'status': 'loaded'}
        elif students is None:
            train_metrics = risk_model.train()
        else:
            train_metrics = {
                'status': 'heuristic',
                'message': 'No school model is available; assigned students use heuristic estimates.',
            }

    if students is None:
        students = Student.objects.filter(is_active=True)
    else:
        students = students.filter(is_active=True).distinct()
    students_to_score = list(students)
    predictions = []
    for student in students_to_score:
        prediction = predict_student(student)
        if prediction is not None:
            predictions.append(prediction)

    summary = {
        'trained': train_metrics,
        'students_scored': len(predictions),
        'students_unassessed': len(students_to_score) - len(predictions),
        'high_risk': sum(1 for p in predictions if p.risk_level == RiskPrediction.RiskLevel.HIGH),
        'medium_risk': sum(1 for p in predictions if p.risk_level == RiskPrediction.RiskLevel.MEDIUM),
        'low_risk': sum(1 for p in predictions if p.risk_level == RiskPrediction.RiskLevel.LOW),
        'declining': sum(1 for p in predictions if p.is_declining),
    }
    return summary


def _with_latest_student_data(students, assessment_queryset=None):
    if assessment_queryset is None:
        assessment_queryset = Assessment.objects.order_by('date', 'id')
    return students.select_related('classroom').prefetch_related(
        Prefetch(
            'risk_predictions',
            queryset=RiskPrediction.objects.order_by('-predicted_at', '-id'),
            to_attr='dashboard_predictions',
        ),
        Prefetch(
            'attendance_snapshots',
            queryset=AttendanceSnapshot.objects.order_by('-date', '-id'),
            to_attr='dashboard_attendance_snapshots',
        ),
        Prefetch(
            'attendance_records',
            queryset=AttendanceRecord.objects.order_by('-date', '-id'),
            to_attr='dashboard_attendance_records',
        ),
        Prefetch(
            'assessments',
            queryset=assessment_queryset,
            to_attr='dashboard_assessments',
        ),
    )


def _latest_attendance_rate(student):
    snapshots = student.dashboard_attendance_snapshots
    records = student.dashboard_attendance_records
    latest_snapshot = snapshots[0] if snapshots else None
    latest_record_date = records[0].date if records else None
    if latest_snapshot and (
        latest_record_date is None or latest_snapshot.date >= latest_record_date
    ):
        return latest_snapshot.attendance_rate
    if records:
        present_statuses = {
            AttendanceRecord.Status.PRESENT,
            AttendanceRecord.Status.LATE,
            AttendanceRecord.Status.EXCUSED,
        }
        return sum(record.status in present_statuses for record in records) / len(records)
    if latest_snapshot:
        return latest_snapshot.attendance_rate
    return None


def dashboard_summary(students=None) -> dict:
    if students is None:
        students = Student.objects.filter(is_active=True)
    else:
        students = students.filter(is_active=True).distinct()
    students = _with_latest_student_data(students)
    total = students.count()
    high = medium = low = declining = unassessed = 0
    attendance_rates = []

    for student in students:
        predictions = student.dashboard_predictions
        latest = predictions[0] if predictions else None
        attendance_rate = _latest_attendance_rate(student)
        if attendance_rate is not None:
            attendance_rates.append(attendance_rate)
        if not latest:
            unassessed += 1
            continue
        if latest.risk_level == RiskPrediction.RiskLevel.HIGH:
            high += 1
        elif latest.risk_level == RiskPrediction.RiskLevel.MEDIUM:
            medium += 1
        else:
            low += 1
        if latest.is_declining:
            declining += 1

    open_alerts = Alert.objects.filter(
        student__in=students,
        is_acknowledged=False,
    ).count()
    return {
        'total_learners': total,
        'on_track': low,
        'need_attention': medium,
        'high_risk': high,
        'at_risk': high + medium,
        'declining': declining,
        'unassessed': unassessed,
        'open_alerts': open_alerts,
        'average_attendance': (
            round(sum(attendance_rates) / len(attendance_rates) * 100, 1)
            if attendance_rates
            else None
        ),
    }


def classroom_performance_rows(students=None, assessment_queryset=None) -> list[dict]:
    classrooms = {}
    if students is None:
        students = Student.objects.filter(is_active=True)
    else:
        students = students.filter(is_active=True).distinct()
    students = _with_latest_student_data(
        students.filter(classroom__isnull=False),
        assessment_queryset=assessment_queryset,
    )
    for student in students:
        row = classrooms.setdefault(
            student.classroom_id,
            {
                'id': student.classroom_id,
                'name': student.classroom.name,
                'academic_year': student.classroom.academic_year,
                'term': student.classroom.term,
                'student_count': 0,
                'high_risk': 0,
                'medium_risk': 0,
                'scores': [],
                'attendance_rates': [],
            },
        )
        row['student_count'] += 1
        predictions = student.dashboard_predictions
        latest = predictions[0] if predictions else None
        if latest:
            if latest.risk_level == RiskPrediction.RiskLevel.HIGH:
                row['high_risk'] += 1
            elif latest.risk_level == RiskPrediction.RiskLevel.MEDIUM:
                row['medium_risk'] += 1
        student_scores = [assessment.percentage for assessment in student.dashboard_assessments]
        if student_scores:
            row['scores'].append(sum(student_scores) / len(student_scores))
        elif assessment_queryset is None and latest and latest.average_score is not None:
            row['scores'].append(latest.average_score)
        attendance_rate = _latest_attendance_rate(student)
        if attendance_rate is not None:
            row['attendance_rates'].append(attendance_rate)

    results = []
    for row in classrooms.values():
        scores = row.pop('scores')
        attendance_rates = row.pop('attendance_rates')
        row['average_score'] = sum(scores) / len(scores) if scores else None
        row['average_attendance'] = (
            sum(attendance_rates) / len(attendance_rates) * 100
            if attendance_rates
            else None
        )
        row['at_risk'] = row['high_risk'] + row['medium_risk']
        results.append(row)
    return sorted(results, key=lambda row: row['name'])


def risk_report_rows(students=None, assessment_queryset=None) -> list[dict]:
    rows = []
    if students is None:
        students = Student.objects.filter(is_active=True)
    else:
        students = students.filter(is_active=True).distinct()
    for student in _with_latest_student_data(
        students,
        assessment_queryset=assessment_queryset,
    ):
        predictions = student.dashboard_predictions
        latest = predictions[0] if predictions else None
        attendance_rate = _latest_attendance_rate(student)
        student_scores = [
            assessment.percentage for assessment in student.dashboard_assessments
        ]
        average_score = (
            sum(student_scores) / len(student_scores)
            if student_scores
            else (latest.average_score if latest and assessment_queryset is None else None)
        )
        rows.append(
            {
                'id': student.id,
                'student_id': student.student_id,
                'name': student.full_name,
                'classroom': student.classroom.name if student.classroom else '',
                'average': average_score,
                'attendance': attendance_rate * 100 if attendance_rate is not None else None,
                'failure_risk': (latest.failure_probability * 100) if latest else None,
                'risk_level': latest.risk_level if latest else 'unassessed',
                'is_declining': latest.is_declining if latest else False,
                'trend_slope': latest.trend_slope if latest else None,
            }
        )
    rows.sort(key=lambda r: (-(r['failure_risk'] or 0), r['name']))
    return rows
