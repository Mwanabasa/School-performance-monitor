"""Feature engineering for student risk prediction using Pandas."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from django.conf import settings

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


def compute_student_features(student: Student) -> dict[str, Any]:
    assessments = list(
        student.assessments.exclude(assessment_type=Assessment.AssessmentType.ENDTERM)
        .order_by('date')
        .values('assessment_type', 'score', 'max_score', 'date')
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

    attendance = list(student.attendance_records.values_list('status', flat=True))
    if attendance:
        presentish = sum(
            1
            for s in attendance
            if s in (
                AttendanceRecord.Status.PRESENT,
                AttendanceRecord.Status.LATE,
                AttendanceRecord.Status.EXCUSED,
            )
        )
        attendance_rate = presentish / len(attendance)
    else:
        attendance_rate = 1.0

    is_declining = trend_slope < -2.0 and len(percentages) >= 3

    features = {
        'student_id': student.id,
        'avg_score': _safe_mean(percentages),
        'attendance_rate': float(attendance_rate),
        'trend_slope': trend_slope,
        'test_avg': by_type.get(Assessment.AssessmentType.TEST, _safe_mean(percentages)),
        'assignment_avg': by_type.get(
            Assessment.AssessmentType.ASSIGNMENT, _safe_mean(percentages)
        ),
        'project_avg': by_type.get(Assessment.AssessmentType.PROJECT, _safe_mean(percentages)),
        'midterm_score': by_type.get(Assessment.AssessmentType.MIDTERM, _safe_mean(percentages)),
        'score_std': score_std,
        'assessment_count': int(len(percentages)),
        'recent_avg': recent_avg,
        'is_declining': int(is_declining),
    }
    return features


def build_feature_frame(students=None) -> pd.DataFrame:
    if students is None:
        students = Student.objects.filter(is_active=True).prefetch_related(
            'assessments', 'attendance_records'
        )
    rows = [compute_student_features(s) for s in students]
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
        'assessments', 'attendance_records'
    )
    feature_rows = []
    labels = []
    for student in students:
        endterms = student.assessments.filter(
            assessment_type=Assessment.AssessmentType.ENDTERM
        ).order_by('-date')
        if not endterms.exists():
            continue
        final = endterms.first()
        pct = final.percentage
        features = compute_student_features(student)
        feature_rows.append(features)
        labels.append(1 if pct < pass_mark else 0)

    if not feature_rows:
        return pd.DataFrame(columns=FEATURE_COLUMNS), pd.Series(dtype=int)

    X = pd.DataFrame(feature_rows)
    y = pd.Series(labels, name='failed')
    return X[FEATURE_COLUMNS], y
