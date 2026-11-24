"""Import student academic records from Excel/CSV via Pandas."""
from __future__ import annotations

import pandas as pd
from django.db import transaction

from .models import Assessment, AttendanceRecord, Classroom, Student


REQUIRED_STUDENT_COLUMNS = {'student_id', 'first_name', 'last_name'}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.lower()
        .str.replace(' ', '_')
        .str.replace('-', '_')
    )
    return df


def _read_upload(upload) -> pd.DataFrame:
    name = getattr(upload, 'name', 'upload.xlsx').lower()
    if name.endswith('.csv'):
        return pd.read_csv(upload)
    return pd.read_excel(upload)


@transaction.atomic
def import_students_from_excel(upload) -> dict:
    df = _normalize_columns(_read_upload(upload))
    missing = REQUIRED_STUDENT_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f'Missing required columns: {", ".join(sorted(missing))}')

    created_students = 0
    updated_students = 0
    assessments_created = 0
    attendance_created = 0

    classroom = None
    if 'classroom' in df.columns:
        class_name = str(df['classroom'].dropna().iloc[0]) if df['classroom'].notna().any() else None
        if class_name:
            classroom, _ = Classroom.objects.get_or_create(
                name=class_name,
                defaults={'academic_year': '2025', 'term': 'Term 1'},
            )

    for _, row in df.iterrows():
        student_id = str(row['student_id']).strip()
        defaults = {
            'first_name': str(row['first_name']).strip(),
            'last_name': str(row['last_name']).strip(),
            'is_active': True,
        }
        if classroom:
            defaults['classroom'] = classroom
        if 'gender' in df.columns and pd.notna(row.get('gender')):
            gender = str(row['gender']).strip().upper()[:1]
            if gender in {'M', 'F', 'O'}:
                defaults['gender'] = gender
        if 'guardian_name' in df.columns and pd.notna(row.get('guardian_name')):
            defaults['guardian_name'] = str(row['guardian_name'])
        if 'guardian_phone' in df.columns and pd.notna(row.get('guardian_phone')):
            defaults['guardian_phone'] = str(row['guardian_phone'])

        student, created = Student.objects.update_or_create(
            student_id=student_id,
            defaults=defaults,
        )
        created_students += int(created)
        updated_students += int(not created)

        # Optional wide-format assessment columns: test_1, assignment_1, midterm, etc.
        for col in df.columns:
            value = row.get(col)
            if pd.isna(value):
                continue
            assessment_type = None
            title = col.replace('_', ' ').title()
            if col.startswith('test'):
                assessment_type = Assessment.AssessmentType.TEST
            elif col.startswith('assignment'):
                assessment_type = Assessment.AssessmentType.ASSIGNMENT
            elif col.startswith('project'):
                assessment_type = Assessment.AssessmentType.PROJECT
            elif col in ('midterm', 'mid_term'):
                assessment_type = Assessment.AssessmentType.MIDTERM
            elif col in ('endterm', 'end_term', 'final'):
                assessment_type = Assessment.AssessmentType.ENDTERM
            if assessment_type is None:
                continue
            try:
                score = float(value)
            except (TypeError, ValueError):
                continue
            Assessment.objects.create(
                student=student,
                assessment_type=assessment_type,
                title=title,
                score=score,
            )
            assessments_created += 1

        if 'attendance_rate' in df.columns and pd.notna(row.get('attendance_rate')):
            # Expand a single attendance rate into representative present/absent days.
            try:
                rate = float(row['attendance_rate'])
            except (TypeError, ValueError):
                rate = None
            if rate is not None:
                if rate > 1:
                    rate = rate / 100.0
                rate = max(0.0, min(1.0, rate))
                present_days = int(round(rate * 20))
                for day in range(1, 21):
                    status = (
                        AttendanceRecord.Status.PRESENT
                        if day <= present_days
                        else AttendanceRecord.Status.ABSENT
                    )
                    _, was_created = AttendanceRecord.objects.get_or_create(
                        student=student,
                        date=pd.Timestamp('2025-01-01') + pd.Timedelta(days=day - 1),
                        defaults={'status': status},
                    )
                    attendance_created += int(was_created)

    return {
        'students_created': created_students,
        'students_updated': updated_students,
        'assessments_created': assessments_created,
        'attendance_records_created': attendance_created,
        'rows_processed': len(df),
    }
