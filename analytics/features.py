"""Feature engineering for student risk prediction using Pandas."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from django.conf import settings
from django.db.models import Q

from students.models import Assessment, AttendanceRecord, Student

FEATURE_COLUMNS = [
    'avg_score',
    'attendance_rate',
    'trend_slope',
    'test_avg',
    'assignment_avg',
    'project_avg',
    'midterm_score',
    'score_std',
    'assessment_count',
    'recent_avg',
    'is_declining',
]


def _safe_mean(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    return float(series.mean())


def compute_student_features(student: Student, before_assessment=None) -> dict[str, Any]:
    assessments_query = student.assessments.order_by('date', 'id')
    attendance_query = student.attendance_records.all()
    attendance_snapshot_query = student.attendance_snapshots.order_by('-date', '-id')
    if before_assessment is not None:
        assessments_query = assessments_query.filter(
            Q(date__lt=before_assessment.date)
            | Q(date=before_assessment.date, id__lt=before_assessment.id)
        )
        attendance_query = attendance_query.filter(date__lte=before_assessment.date)
        attendance_snapshot_query = attendance_snapshot_query.filter(
            date__lte=before_assessment.date
        )

    assessments = list(
        assessments_query.values('assessment_type', 'score', 'max_score', 'date')
    )
    df = pd.DataFrame(assessments)
    if df.empty:
        percentages = pd.Series(dtype=float)
        trend_slope = 0.0
        score_std = 0.0
        recent_avg = 0.0
        by_type = {}
    else:
        df['percentage'] = (df['score'] / df['max_score'].replace(0, np.nan)) * 100
        df['percentage'] = df['percentage'].fillna(0)
        percentages = df['percentage']
        if len(percentages) >= 2:
            x = np.arange(len(percentages))
            trend_slope = float(np.polyfit(x, percentages.values, 1)[0])
        else:
            trend_slope = 0.0
        score_std = float(percentages.std(ddof=0)) if len(percentages) else 0.0
        recent_avg = float(percentages.tail(3).mean())
        by_type = {
            t: float(g['percentage'].mean())
            for t, g in df.groupby('assessment_type')
        }

    attendance = list(attendance_query.values_list('date', 'status'))
    latest_snapshot = attendance_snapshot_query.first()
    latest_attendance_date = max((record_date for record_date, _ in attendance), default=None)
    if latest_snapshot and (
        latest_attendance_date is None or latest_snapshot.date >= latest_attendance_date
    ):
        attendance_rate = latest_snapshot.attendance_rate
    elif attendance:
        presentish = sum(
            1
            for _, status in attendance
            if status in (
                AttendanceRecord.Status.PRESENT,
                AttendanceRecord.Status.LATE,
                AttendanceRecord.Status.EXCUSED,
            )
        )
        attendance_rate = presentish / len(attendance)
    elif latest_snapshot:
        attendance_rate = latest_snapshot.attendance_rate
    else:
        attendance_rate = 1.0

    recent_scores = percentages.tail(4).tolist()
    is_declining = len(recent_scores) == 4 and all(
        later < earlier for earlier, later in zip(recent_scores, recent_scores[1:])
    )
    test_score_values = (
        df.loc[
            df['assessment_type'].isin(
                (Assessment.AssessmentType.QUIZ, Assessment.AssessmentType.TEST)
            ),
            'percentage',
        ]
        if not df.empty
        else pd.Series(dtype=float)
    )

    features = {
        'student_id': student.id,
        'avg_score': _safe_mean(percentages),
        'attendance_rate': float(attendance_rate),
        'trend_slope': trend_slope,
        'test_avg': float(test_score_values.mean())
        if not test_score_values.empty
        else _safe_mean(percentages),
        'assignment_avg': by_type.get(
            Assessment.AssessmentType.ASSIGNMENT, _safe_mean(percentages)
        ),
        'project_avg': by_type.get(Assessment.AssessmentType.PROJECT, _safe_mean(percentages)),
        'midterm_score': by_type.get(Assessment.AssessmentType.MIDTERM, _safe_mean(percentages)),
        'score_std': score_std,
        'assessment_count': int(len(percentages)),
        'recent_avg': recent_avg,
        'is_declining': int(is_declining),
        'has_attendance_data': bool(attendance or latest_snapshot),
    }
    return features


def build_feature_frame(students=None) -> pd.DataFrame:
    if students is None:
        students = Student.objects.filter(is_active=True).prefetch_related(
            'assessments', 'attendance_records', 'attendance_snapshots'
        )
    rows = []
    for student in students:
        features = compute_student_features(student)
        if features['assessment_count'] > 0:
            rows.append(features)
    if not rows:
        return pd.DataFrame(columns=['student_id'] + FEATURE_COLUMNS)
    return pd.DataFrame(rows)


def build_training_frame() -> tuple[pd.DataFrame, pd.Series]:
    """
    Build supervised labels from students who already have an end-of-term score.
    Label = 1 if failed (score < PASS_MARK), else 0.
    """
    pass_mark = settings.PASS_MARK
    students = Student.objects.filter(is_active=True).prefetch_related(
        'assessments', 'attendance_records', 'attendance_snapshots'
    )
    feature_rows = []
    labels = []
    for student in students:
        endterms = student.assessments.filter(
            assessment_type=Assessment.AssessmentType.ENDTERM
        ).order_by('date', 'id')
        for final in endterms:
            features = compute_student_features(student, before_assessment=final)
            if features['assessment_count'] == 0:
                continue
            feature_rows.append(features)
            labels.append(1 if final.percentage < pass_mark else 0)

    if not feature_rows:
        return pd.DataFrame(columns=FEATURE_COLUMNS), pd.Series(dtype=int)

    X = pd.DataFrame(feature_rows)
    y = pd.Series(labels, name='failed')
    return X[FEATURE_COLUMNS], y
