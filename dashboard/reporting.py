from collections import defaultdict

from django.utils import timezone
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from django.conf import settings

from analytics.risk_service import (
    classroom_performance_rows,
    dashboard_summary,
    risk_report_rows,
)
from students.models import (
    Alert,
    Assessment,
    AttendanceRecord,
    AttendanceSnapshot,
    Intervention,
    Student,
)


def _style_header(sheet, header_row):
    header_fill = PatternFill(fill_type='solid', fgColor='0F6E56')
    for cell in sheet[header_row]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = header_fill
        cell.alignment = Alignment(vertical='center')


def _format_sheet(sheet, header_row=1, add_filter=True):
    _style_header(sheet, header_row)
    for column in sheet.columns:
        column_letter = get_column_letter(column[0].column)
        max_length = max(
            (len(str(cell.value)) for cell in column if cell.value is not None),
            default=0,
        )
        sheet.column_dimensions[column_letter].width = min(max(max_length + 2, 12), 48)

    sheet.freeze_panes = f'A{header_row + 1}'
    if add_filter:
        sheet.auto_filter.ref = sheet.dimensions


def build_performance_workbook(students=None, assessment_queryset=None):
    if students is None:
        students = Student.objects.filter(is_active=True)
    else:
        students = students.filter(is_active=True).distinct()
    if assessment_queryset is None:
        assessment_queryset = Assessment.objects.filter(student__in=students)
    assessment_query = assessment_queryset.select_related('student', 'student__classroom')
    assessments = list(
        assessment_query.order_by(
            'student__last_name', 'student__first_name', 'date', 'id'
        )
    )

    workbook = Workbook()
    overview = workbook.active
    overview.title = 'Overview'
    overview.append(['Student Performance Report'])
    overview['A1'].font = Font(size=16, bold=True, color='0F6E56')
    overview.append(['Generated', timezone.localdate()])
    overview.append([])
    overview.append(['Metric', 'Value'])

    summary = dashboard_summary(students=students)
    overview.append(['Total students', summary['total_learners']])
    overview.append(['On track', summary['on_track']])
    overview.append(['Need attention', summary['need_attention']])
    overview.append(['High risk', summary['high_risk']])
    overview.append(['Students at risk', summary['at_risk']])
    overview.append(['Declining', summary['declining']])
    overview.append(['Open alerts', summary['open_alerts']])
    overview.append(['Average attendance (%)', summary['average_attendance']])

    rows = risk_report_rows(
        students=students,
        assessment_queryset=assessment_query,
    )
    risk_counts = {
        level: sum(1 for row in rows if row['risk_level'] == level)
        for level in ('low', 'medium', 'high', 'unassessed')
    }
    overview.append(['Risk level', 'Students'])
    risk_header_row = overview.max_row
    for level, count in risk_counts.items():
        overview.append([level.title(), count])
    _style_header(overview, risk_header_row)

    risk_chart = BarChart()
    risk_chart.type = 'col'
    risk_chart.title = 'Students by risk level'
    risk_chart.y_axis.title = 'Students'
    risk_chart.x_axis.title = 'Risk level'
    risk_chart.add_data(
        Reference(
            overview,
            min_col=2,
            min_row=risk_header_row,
            max_row=risk_header_row + len(risk_counts),
        ),
        titles_from_data=True,
    )
    risk_chart.set_categories(
        Reference(
            overview,
            min_col=1,
            min_row=risk_header_row + 1,
            max_row=risk_header_row + len(risk_counts),
        )
    )
    risk_chart.height = 7
    risk_chart.width = 13
    overview.add_chart(risk_chart, 'D4')

    scores_by_date = defaultdict(list)
    for assessment in assessments:
        key = (assessment.date, assessment.get_assessment_type_display())
        scores_by_date[key].append(assessment.percentage)
    overview.append(['Assessment date', 'Average score (%)'])
    trend_header_row = overview.max_row
    _style_header(overview, trend_header_row)
    for (assessment_date, assessment_type), scores in sorted(scores_by_date.items()):
        overview.append(
            [f'{assessment_date} - {assessment_type}', sum(scores) / len(scores)]
        )

    if scores_by_date:
        trend_chart = LineChart()
        trend_chart.title = 'Average performance over time'
        trend_chart.y_axis.title = 'Average score (%)'
        trend_chart.x_axis.title = 'Assessment date'
        trend_chart.add_data(
            Reference(
                overview,
                min_col=2,
                min_row=trend_header_row,
                max_row=overview.max_row,
            ),
            titles_from_data=True,
        )
        trend_chart.set_categories(
            Reference(
                overview,
                min_col=1,
                min_row=trend_header_row + 1,
                max_row=overview.max_row,
            )
        )
        trend_chart.height = 8
        trend_chart.width = 16
        overview.add_chart(trend_chart, 'D19')
    _format_sheet(overview, header_row=4, add_filter=False)

    classroom_sheet = workbook.create_sheet('Classroom Summary')
    classroom_sheet.append(
        [
            'Academic year',
            'Term',
            'Classroom',
            'Students',
            'Average score (%)',
            'Average attendance (%)',
            'At risk',
            'High risk',
        ]
    )
    classroom_rows = classroom_performance_rows(
        students=students,
        assessment_queryset=assessment_query,
    )
    for row in classroom_rows:
        classroom_sheet.append(
            [
                row['academic_year'],
                row['term'],
                row['name'],
                row['student_count'],
                row['average_score'],
                row['average_attendance'],
                row['at_risk'],
                row['high_risk'],
            ]
        )
    _format_sheet(classroom_sheet)

    term_groups = defaultdict(lambda: {'scores': [], 'students': set()})
    for assessment in assessments:
        classroom = assessment.student.classroom
        key = (
            assessment.academic_year or 'Unspecified',
            assessment.term or 'Unspecified',
            classroom.name if classroom else 'Unassigned',
            assessment.subject or 'Unspecified',
            assessment.get_assessment_type_display(),
        )
        term_groups[key]['scores'].append(assessment.percentage)
        term_groups[key]['students'].add(assessment.student_id)
    term_sheet = workbook.create_sheet('Term Performance')
    term_sheet.append(
        [
            'Academic year',
            'Term',
            'Classroom',
            'Subject',
            'Assessment type',
            'Assessments',
            'Students',
            'Average score (%)',
        ]
    )
    for key, group in sorted(term_groups.items()):
        term_sheet.append(
            [
                *key,
                len(group['scores']),
                len(group['students']),
                sum(group['scores']) / len(group['scores']),
            ]
        )
    _format_sheet(term_sheet)

    latest_endterms = {}
    for assessment in sorted(
        (
            item
            for item in assessments
            if item.assessment_type == Assessment.AssessmentType.ENDTERM
        ),
        key=lambda item: (
            item.student_id,
            item.subject,
            item.academic_year,
            item.term,
            -item.date.toordinal(),
            -item.id,
        ),
    ):
        latest_endterms.setdefault(
            (
                assessment.student_id,
                assessment.subject,
                assessment.academic_year,
                assessment.term,
            ),
            assessment,
        )

    outcome_sheet = workbook.create_sheet('Pass Fail Summary')
    outcome_sheet.append(
        [
            'Academic year',
            'Term',
            'Classroom',
            'Subject',
            'Students with results',
            'Pass',
            'Fail',
            'Pass rate (%)',
        ]
    )
    outcomes = defaultdict(lambda: {'pass': 0, 'fail': 0})
    for assessment in latest_endterms.values():
        classroom = assessment.student.classroom
        year = assessment.academic_year or 'Unspecified'
        term = assessment.term or 'Unspecified'
        classroom_name = classroom.name if classroom else 'Unassigned'
        key = (year, term, classroom_name, assessment.subject or 'Unspecified')
        outcome = 'pass' if assessment.percentage >= settings.PASS_MARK else 'fail'
        outcomes[key][outcome] += 1
    for (year, term, classroom_name, subject), counts in sorted(outcomes.items()):
        total = counts['pass'] + counts['fail']
        outcome_sheet.append(
            [
                year,
                term,
                classroom_name,
                subject,
                total,
                counts['pass'],
                counts['fail'],
                counts['pass'] / total * 100,
            ]
        )
    pass_total = sum(counts['pass'] for counts in outcomes.values())
    fail_total = sum(counts['fail'] for counts in outcomes.values())
    total_outcomes = pass_total + fail_total
    outcome_sheet.append(
        [
            '',
            '',
            'School total',
            '',
            total_outcomes,
            pass_total,
            fail_total,
            pass_total / total_outcomes * 100 if total_outcomes else 0,
        ]
    )
    _format_sheet(outcome_sheet)

    student_sheet = workbook.create_sheet('Student Summary')
    student_sheet.append(
        [
            'Student ID',
            'Student',
            'Classroom',
            'Average score (%)',
            'Attendance (%)',
            'Failure risk (%)',
            'Risk level',
            'Declining',
        ]
    )
    for row in rows:
        student_sheet.append(
            [
                row['student_id'],
                row['name'],
                row['classroom'],
                row['average'],
                row['attendance'],
                row['failure_risk'],
                row['risk_level'],
                'Yes' if row['is_declining'] else 'No',
            ]
        )
    _format_sheet(student_sheet)

    assessment_sheet = workbook.create_sheet('Assessment History')
    assessment_sheet.append(
        [
            'Student ID',
            'Student',
            'Classroom',
            'Subject',
            'Academic year',
            'Term',
            'Date',
            'Assessment type',
            'Title',
            'Score',
            'Maximum score',
            'Percentage (%)',
        ]
    )
    for assessment in assessments:
        assessment_sheet.append(
            [
                assessment.student.student_id,
                assessment.student.full_name,
                assessment.student.classroom.name if assessment.student.classroom else '',
                assessment.subject,
                assessment.academic_year,
                assessment.term,
                assessment.date,
                assessment.get_assessment_type_display(),
                assessment.title,
                assessment.score,
                assessment.max_score,
                assessment.percentage,
            ]
        )
    _format_sheet(assessment_sheet)

    attendance_sheet = workbook.create_sheet('Attendance History')
    attendance_sheet.append(
        ['Student ID', 'Student', 'Record type', 'Date', 'Attendance rate (%)', 'Status']
    )
    attendance_rows = []
    for snapshot in AttendanceSnapshot.objects.filter(student__in=students).select_related(
        'student'
    ).order_by('date'):
        attendance_rows.append(
            [
                snapshot.student.student_id,
                snapshot.student.full_name,
                'Rate snapshot',
                snapshot.date,
                snapshot.attendance_rate * 100,
                '',
            ]
        )
    for record in AttendanceRecord.objects.filter(student__in=students).select_related(
        'student'
    ).order_by('date'):
        attendance_rows.append(
            [
                record.student.student_id,
                record.student.full_name,
                'Daily record',
                record.date,
                '',
                record.get_status_display(),
            ]
        )
    attendance_rows.sort(key=lambda row: (row[3], row[0], row[2]))
    for row in attendance_rows:
        attendance_sheet.append(row)
    _format_sheet(attendance_sheet)

    action_sheet = workbook.create_sheet('Alerts & Interventions')
    action_sheet.append(['Student ID', 'Student', 'Record', 'Date', 'Status / Severity', 'Details'])
    for alert in Alert.objects.filter(student__in=students).select_related('student').order_by(
        '-created_at'
    ):
        status = 'Acknowledged' if alert.is_acknowledged else 'Open'
        action_sheet.append(
            [
                alert.student.student_id,
                alert.student.full_name,
                alert.get_alert_type_display(),
                alert.created_at.date(),
                f'{alert.get_severity_display()} / {status}',
                alert.message,
            ]
        )
    for intervention in Intervention.objects.filter(student__in=students).select_related(
        'student'
    ).order_by('-created_at'):
        status = 'Completed' if intervention.is_completed else 'Suggested'
        action_sheet.append(
            [
                intervention.student.student_id,
                intervention.student.full_name,
                intervention.get_action_display(),
                intervention.created_at.date(),
                status,
                intervention.reason,
            ]
        )
    _format_sheet(action_sheet)
    return workbook
