"""Import student academic records from Excel/CSV via Pandas."""
from __future__ import annotations

from zipfile import BadZipFile

import pandas as pd
from django.db import transaction
from django.utils import timezone

from .models import Assessment, AttendanceSnapshot, Classroom, Student


REQUIRED_STUDENT_COLUMNS = {'student_id', 'first_name', 'last_name'}


def _assessment_type_for_column(column: str) -> str | None:
    if column.startswith('quiz'):
        return Assessment.AssessmentType.QUIZ
    if column.startswith('test'):
        return Assessment.AssessmentType.TEST
    if column.startswith('assignment'):
        return Assessment.AssessmentType.ASSIGNMENT
    if column.startswith('project'):
        return Assessment.AssessmentType.PROJECT
    if column in ('midterm', 'mid_term'):
        return Assessment.AssessmentType.MIDTERM
    if column in ('endterm', 'end_term', 'final'):
        return Assessment.AssessmentType.ENDTERM
    return None


def _assessment_column_order(column: str) -> tuple[int, int, str]:
    prefixes = ('quiz', 'test', 'assignment', 'project', 'midterm', 'endterm')
    for order, prefix in enumerate(prefixes):
        if column.startswith(prefix):
            suffix = column[len(prefix):].lstrip('_')
            try:
                number = int(suffix)
            except ValueError:
                number = 0
            return order, number, column
    return len(prefixes), 0, column


def _parse_optional_date(value, column: str):
    if pd.isna(value) or (isinstance(value, str) and not value.strip()):
        return None
    parsed = pd.to_datetime(value, errors='coerce')
    if pd.isna(parsed):
        raise ValueError(f'Invalid date in {column}: {value!r}')
    return parsed.date()


def record_attendance_rate(student: Student, value: float, period_end=None) -> int:
    rate = float(value)
    if rate > 1:
        rate /= 100.0
    rate = max(0.0, min(1.0, rate))
    _, was_created = AttendanceSnapshot.objects.update_or_create(
        student=student,
        date=period_end or timezone.localdate(),
        defaults={'attendance_rate': rate},
    )
    return int(was_created)


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
    try:
        if name.endswith('.csv'):
            return pd.read_csv(upload)
        return pd.read_excel(upload)
    except (ValueError, pd.errors.ParserError, BadZipFile) as exc:
        raise ValueError('The uploaded file could not be read as a valid Excel or CSV file.') from exc


@transaction.atomic
def import_students_from_excel(upload, allowed_classrooms=None, allowed_subjects=None) -> dict:
    df = _normalize_columns(_read_upload(upload))
    missing = REQUIRED_STUDENT_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f'Missing required columns: {", ".join(sorted(missing))}')

    created_students = 0
    updated_students = 0
    assessments_created = 0
    attendance_created = 0

    assessment_columns = sorted(
        (column for column in df.columns if _assessment_type_for_column(column)),
        key=_assessment_column_order,
    )

    restricted_classrooms = allowed_classrooms is not None
    classroom_options = list(allowed_classrooms) if restricted_classrooms else []
    classroom_by_name = {classroom.name: classroom for classroom in classroom_options}
    classroom_ids = {classroom.id for classroom in classroom_options}
    subject_options = allowed_subjects or {}

    for _, row in df.iterrows():
        student_id = str(row['student_id']).strip()
        existing = Student.objects.select_related('classroom').filter(
            student_id=student_id
        ).first()
        defaults = {
            'first_name': str(row['first_name']).strip(),
            'last_name': str(row['last_name']).strip(),
            'is_active': True,
        }
        classroom_name = None
        if 'classroom' in df.columns and pd.notna(row.get('classroom')):
            classroom_name = str(row['classroom']).strip() or None
        classroom_defaults = {}
        if 'academic_year' in df.columns and pd.notna(row.get('academic_year')):
            classroom_defaults['academic_year'] = str(row['academic_year']).strip()
        if 'term' in df.columns and pd.notna(row.get('term')):
            classroom_defaults['term'] = str(row['term']).strip()

        if restricted_classrooms:
            if existing and existing.classroom_id not in classroom_ids:
                raise ValueError(
                    f'Student {student_id} is not in one of your assigned classrooms.'
                )
            if classroom_name:
                classroom = classroom_by_name.get(classroom_name)
                if classroom is None:
                    raise ValueError(
                        f'Classroom "{classroom_name}" is not assigned to your account.'
                    )
            elif existing and existing.classroom_id in classroom_ids:
                classroom = existing.classroom
            elif len(classroom_options) == 1:
                classroom = classroom_options[0]
            else:
                raise ValueError(
                    f'Choose an assigned classroom for student {student_id} in the spreadsheet.'
                )
            defaults['classroom'] = classroom
        elif classroom_name:
            classroom, _ = Classroom.objects.get_or_create(
                name=classroom_name,
                defaults=classroom_defaults,
            )
            defaults['classroom'] = classroom

        subject_name = (
            str(row['subject']).strip()
            if 'subject' in df.columns and pd.notna(row.get('subject'))
            else ''
        )
        has_scores = any(pd.notna(row.get(column)) for column in assessment_columns)
        if restricted_classrooms and has_scores:
            assigned_subjects = subject_options.get(classroom.id, set())
            if not subject_name and len(assigned_subjects) == 1:
                subject_name = next(iter(assigned_subjects))
            if not subject_name:
                raise ValueError(
                    f'Select a subject for the assessment scores for student {student_id}.'
                )
            if subject_name not in assigned_subjects:
                raise ValueError(
                    f'Subject "{subject_name}" is not assigned to you in "{classroom.name}".'
                )

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
        for col in assessment_columns:
            value = row.get(col)
            if pd.isna(value):
                continue
            assessment_type = _assessment_type_for_column(col)
            title = col.replace('_', ' ').title()
            if assessment_type is None:
                continue
            try:
                score = float(value)
            except (TypeError, ValueError):
                continue
            Assessment.objects.create(
                student=student,
                subject=subject_name,
                academic_year=(
                    str(row['academic_year']).strip()
                    if 'academic_year' in df.columns and pd.notna(row.get('academic_year'))
                    else ''
                ),
                term=(
                    str(row['term']).strip()
                    if 'term' in df.columns and pd.notna(row.get('term'))
                    else ''
                ),
                assessment_type=assessment_type,
                title=title,
                score=score,
                date=(
                    _parse_optional_date(row.get(f'{col}_date'), f'{col}_date')
                    or _parse_optional_date(row.get('assessment_date'), 'assessment_date')
                    or timezone.localdate()
                ),
            )
            assessments_created += 1

        if 'attendance_rate' in df.columns and pd.notna(row.get('attendance_rate')):
            try:
                rate = float(row['attendance_rate'])
            except (TypeError, ValueError):
                rate = None
            if rate is not None:
                attendance_date = _parse_optional_date(
                    row.get('attendance_date'), 'attendance_date'
                )
                attendance_created += record_attendance_rate(
                    student, rate, period_end=attendance_date
                )

    return {
        'students_created': created_students,
        'students_updated': updated_students,
        'assessments_created': assessments_created,
        'attendance_records_created': attendance_created,
        'attendance_snapshots_created': attendance_created,
        'rows_processed': len(df),
    }
