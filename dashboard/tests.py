from datetime import date
from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from students.access import TEACHER_GROUP
from students.models import (
    Assessment,
    AttendanceSnapshot,
    Classroom,
    Intervention,
    RiskPrediction,
    Student,
    StudentPromotion,
    TeacherAssignment,
)


class PerformanceReportTests(TestCase):
    def setUp(self):
        admin = get_user_model().objects.create_superuser(
            username='administrator',
            password='test-password',
        )
        self.client.force_login(admin)

    def test_excel_report_contains_student_assessments_and_visual_charts(self):
        classroom = Classroom.objects.create(
            name='S.4 Blue',
            academic_year='2026',
            term='Term 1',
        )
        student = Student.objects.create(
            student_id='REPORT-001',
            first_name='Grace',
            last_name='Namukasa',
            classroom=classroom,
        )
        Assessment.objects.create(
            student=student,
            assessment_type=Assessment.AssessmentType.TEST,
            title='Test 1',
            score=82,
            date=date(2025, 3, 10),
            subject='Mathematics',
        )
        Assessment.objects.create(
            student=student,
            assessment_type=Assessment.AssessmentType.ENDTERM,
            title='Term 1 final',
            score=82,
            date=date(2025, 3, 20),
            subject='Mathematics',
        )
        RiskPrediction.objects.create(
            student=student,
            failure_probability=0.1,
            risk_level=RiskPrediction.RiskLevel.LOW,
            average_score=82,
            attendance_rate=0.82,
        )
        AttendanceSnapshot.objects.create(
            student=student,
            attendance_rate=0.82,
            date=date(2025, 3, 10),
        )

        response = self.client.get(reverse('dashboard-export-report'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        report = load_workbook(BytesIO(response.content))
        self.assertIn('Student Summary', report.sheetnames)
        self.assertIn('Classroom Summary', report.sheetnames)
        self.assertIn('Pass Fail Summary', report.sheetnames)
        self.assertIn('Assessment History', report.sheetnames)
        self.assertIn('Attendance History', report.sheetnames)
        self.assertEqual(report['Assessment History']['A2'].value, 'REPORT-001')
        self.assertEqual(report['Assessment History']['D2'].value, 'Mathematics')
        self.assertEqual(report['Attendance History']['E2'].value, 82)
        self.assertEqual(report['Pass Fail Summary']['F2'].value, 1)
        self.assertEqual(len(report['Overview']._charts), 2)


class SchoolRoleTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            username='administrator',
            password='test-password',
        )
        self.teacher = User.objects.create_user(
            username='teacher',
            password='test-password',
            first_name='Tina',
            last_name='Teacher',
        )
        self.teacher.groups.add(Group.objects.get_or_create(name=TEACHER_GROUP)[0])
        self.assigned_class = Classroom.objects.create(name='S.3 Science')
        self.other_class = Classroom.objects.create(name='S.4 Arts')
        TeacherAssignment.objects.create(
            teacher=self.teacher,
            classroom=self.assigned_class,
            subject='Mathematics',
        )
        self.assigned_student = Student.objects.create(
            student_id='ROLE-001',
            first_name='Amina',
            last_name='Okello',
            classroom=self.assigned_class,
        )
        self.other_student = Student.objects.create(
            student_id='ROLE-002',
            first_name='Brian',
            last_name='Nakato',
            classroom=self.other_class,
        )

    def test_role_dashboard_redirects_by_role_and_requires_login(self):
        response = self.client.get(reverse('role-dashboard'))
        self.assertRedirects(
            response,
            f'{reverse("login")}?next={reverse("role-dashboard")}',
        )

        self.client.force_login(self.admin)
        self.assertRedirects(response=self.client.get(reverse('role-dashboard')), expected_url=reverse('school-admin-home'))

        self.client.force_login(self.teacher)
        self.assertRedirects(response=self.client.get(reverse('role-dashboard')), expected_url=reverse('dashboard-home'))

    def test_teacher_dashboard_and_api_only_expose_assigned_classrooms(self):
        self.client.force_login(self.teacher)

        dashboard = self.client.get(reverse('dashboard-home'))
        self.assertContains(dashboard, 'Amina Okello')
        self.assertNotContains(dashboard, 'Brian Nakato')
        self.assertContains(dashboard, 'S.3 Science · Mathematics')
        self.assertEqual(
            self.client.get(
                reverse('dashboard-student', args=[self.other_student.id])
            ).status_code,
            404,
        )

        report = self.client.get('/api/analytics/risk-report/')
        self.assertEqual(report.status_code, 200)
        self.assertEqual([row['student_id'] for row in report.json()], ['ROLE-001'])

    def test_teacher_cannot_manage_unassigned_students_or_create_classrooms(self):
        self.client.force_login(self.teacher)
        admin_page = self.client.get(reverse('school-admin-home'))
        self.assertEqual(admin_page.status_code, 302)
        self.assertIn(reverse('login'), admin_page.url)

        self.assertEqual(
            self.client.get(f'/api/students/{self.other_student.id}/').status_code,
            404,
        )

        response = self.client.post(
            '/api/assessments/',
            {
                'student': self.other_student.id,
                'assessment_type': 'test',
                'title': 'Test 1',
                'score': 70,
                'max_score': 100,
                'date': '2026-01-10',
            },
        )
        self.assertEqual(response.status_code, 403)

        response = self.client.post(
            '/api/classrooms/',
            {'name': 'S.5 Biology', 'academic_year': '2026', 'term': 'Term 1'},
        )
        self.assertEqual(response.status_code, 403)

    def test_teacher_can_enter_only_assigned_subject_marks(self):
        self.client.force_login(self.teacher)
        response = self.client.post(
            '/api/assessments/',
            {
                'student': self.assigned_student.id,
                'subject': 'Mathematics',
                'assessment_type': 'test',
                'title': 'Quiz 1',
                'score': 78,
                'max_score': 100,
                'date': '2026-01-10',
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(RiskPrediction.objects.filter(student=self.assigned_student).exists())

        Assessment.objects.create(
            student=self.assigned_student,
            subject='Science',
            assessment_type=Assessment.AssessmentType.TEST,
            title='Science test',
            score=90,
            date=date(2026, 1, 11),
        )
        response = self.client.get('/api/assessments/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item['subject'] for item in response.json()['results']},
            {'Mathematics'},
        )
        student_detail = self.client.get(
            f'/api/students/{self.assigned_student.id}/'
        )
        self.assertEqual(
            {item['subject'] for item in student_detail.json()['assessments']},
            {'Mathematics'},
        )
        page = self.client.get(
            reverse('dashboard-student', args=[self.assigned_student.id])
        )
        self.assertNotContains(page, 'Science test')

    def test_class_report_includes_only_subjects_assigned_in_that_class(self):
        TeacherAssignment.objects.create(
            teacher=self.teacher,
            classroom=self.other_class,
            subject='Science',
        )
        Assessment.objects.create(
            student=self.assigned_student,
            subject='Mathematics',
            assessment_type=Assessment.AssessmentType.TEST,
            title='Math test',
            score=82,
            date=date(2026, 1, 10),
        )
        Assessment.objects.create(
            student=self.assigned_student,
            subject='Science',
            assessment_type=Assessment.AssessmentType.TEST,
            title='Science test',
            score=91,
            date=date(2026, 1, 11),
        )
        for subject, score in (('Mathematics', 82), ('Science', 91)):
            Assessment.objects.create(
                student=self.assigned_student,
                subject=subject,
                assessment_type=Assessment.AssessmentType.ENDTERM,
                title=f'{subject} final',
                score=score,
                date=date(2026, 2, 1),
            )
        self.client.force_login(self.teacher)

        response = self.client.get(
            reverse('dashboard-export-report'),
            {'classroom': self.assigned_class.id},
        )

        self.assertEqual(response.status_code, 200)
        report = load_workbook(BytesIO(response.content))
        self.assertEqual(
            {
                report['Assessment History'].cell(row, 4).value
                for row in range(2, report['Assessment History'].max_row + 1)
            },
            {'Mathematics'},
        )
        self.assertEqual(
            {report['Term Performance'].cell(row, 4).value for row in (2, 3)},
            {'Mathematics'},
        )
        self.assertEqual(report['Pass Fail Summary']['D2'].value, 'Mathematics')

        response = self.client.post(
            '/api/assessments/',
            {
                'student': self.assigned_student.id,
                'subject': 'Science',
                'assessment_type': 'test',
                'title': 'Science quiz',
                'score': 78,
                'max_score': 100,
                'date': '2026-01-12',
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_school_administrator_cannot_enter_marks(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            '/api/assessments/',
            {
                'student': self.assigned_student.id,
                'subject': 'Mathematics',
                'assessment_type': 'test',
                'title': 'Quiz 1',
                'score': 78,
                'max_score': 100,
                'date': '2026-01-10',
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_administrator_dashboard_shows_attendance_and_class_rankings(self):
        self.client.force_login(self.admin)
        for student, score, attendance, probability, level in (
            (
                self.assigned_student,
                80,
                0.80,
                0.70,
                RiskPrediction.RiskLevel.HIGH,
            ),
            (
                self.other_student,
                90,
                0.90,
                0.40,
                RiskPrediction.RiskLevel.MEDIUM,
            ),
        ):
            AttendanceSnapshot.objects.create(
                student=student,
                attendance_rate=attendance,
                date=date(2026, 1, 10),
            )
            RiskPrediction.objects.create(
                student=student,
                failure_probability=probability,
                risk_level=level,
                average_score=score,
                attendance_rate=attendance,
            )

        response = self.client.get(reverse('school-admin-home'))

        self.assertContains(response, 'Students at risk')
        self.assertContains(response, '85%')
        self.assertContains(response, 'S.4 Arts')
        self.assertContains(response, 'S.3 Science')

    def test_administrator_can_plan_interventions_for_high_risk_class(self):
        self.client.force_login(self.admin)
        RiskPrediction.objects.create(
            student=self.assigned_student,
            failure_probability=0.75,
            risk_level=RiskPrediction.RiskLevel.HIGH,
            average_score=35,
        )

        response = self.client.post(
            reverse(
                'school-admin-class-intervention',
                args=[self.assigned_class.id],
            ),
            {
                'action': Intervention.Action.REMEDIAL,
                'reason': 'Organise weekly small-group support.',
            },
        )

        self.assertRedirects(response, reverse('school-admin-home'))
        intervention = Intervention.objects.get(student=self.assigned_student)
        self.assertFalse(intervention.suggested_by_system)
        self.assertIn('weekly small-group support', intervention.reason)

    def test_teacher_can_record_intervention_outcome_for_assigned_student(self):
        self.client.force_login(self.teacher)
        intervention = Intervention.objects.create(
            student=self.assigned_student,
            action=Intervention.Action.REMEDIAL,
            reason='Provide extra practice.',
        )

        response = self.client.post(
            reverse(
                'dashboard-complete-intervention',
                args=[self.assigned_student.id, intervention.id],
            ),
            {'notes': 'Student attended the extra lesson.'},
        )

        self.assertRedirects(
            response,
            reverse('dashboard-student', args=[self.assigned_student.id]),
        )
        intervention.refresh_from_db()
        self.assertTrue(intervention.is_completed)
        self.assertEqual(intervention.notes, 'Student attended the extra lesson.')

    def test_administrator_can_register_and_promote_a_student(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('school-admin-student-create'),
            {
                'student_id': 'ROLE-003',
                'first_name': 'Claire',
                'last_name': 'Mugisha',
                'classroom': self.assigned_class.id,
                'gender': 'F',
                'date_of_birth': '',
                'guardian_name': '',
                'guardian_phone': '',
                'is_active': 'on',
            },
        )
        self.assertRedirects(response, reverse('school-admin-students'))
        student = Student.objects.get(student_id='ROLE-003')
        self.assertEqual(student.classroom, self.assigned_class)

        response = self.client.post(
            reverse('school-admin-student-promote', args=[student.id]),
            {
                'to_classroom': self.other_class.id,
                'promoted_at': '2026-01-10',
                'notes': 'Promoted after year-end results.',
            },
        )
        self.assertRedirects(response, reverse('school-admin-students'))
        student.refresh_from_db()
        promotion = StudentPromotion.objects.get(student=student)
        self.assertEqual(student.classroom, self.other_class)
        self.assertEqual(promotion.from_classroom, self.assigned_class)
        self.assertEqual(promotion.to_classroom, self.other_class)

    def test_administrator_can_create_teacher_and_assign_class_subject(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('school-admin-teacher-create'),
            {
                'username': 'newteacher',
                'first_name': 'Mary',
                'last_name': 'Teacher',
                'email': 'mary@example.test',
                'classrooms': [self.other_class.id],
                'subject': 'English',
                'password1': 'Django-test-Password-2026!',
                'password2': 'Django-test-Password-2026!',
            },
        )

        self.assertRedirects(response, reverse('school-admin-teachers'))
        teacher = get_user_model().objects.get(username='newteacher')
        self.assertTrue(teacher.groups.filter(name=TEACHER_GROUP).exists())
        self.assertTrue(
            TeacherAssignment.objects.filter(
                teacher=teacher,
                classroom=self.other_class,
                subject='English',
            ).exists()
        )
