from datetime import date
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook

from analytics.features import build_training_frame, compute_student_features

from .importers import record_attendance_rate
from .models import (
    Assessment,
    AttendanceRecord,
    AttendanceSnapshot,
    Classroom,
    RiskPrediction,
    Student,
    TeacherAssignment,
)
from .access import TEACHER_GROUP


class StudentEntryTests(TestCase):
    def setUp(self):
        self.classroom = Classroom.objects.create(name='S.3 Science')
        teacher = get_user_model().objects.create_user(
            username='teacher',
            password='test-password',
        )
        teacher.groups.add(Group.objects.get_or_create(name=TEACHER_GROUP)[0])
        TeacherAssignment.objects.create(
            teacher=teacher,
            classroom=self.classroom,
            subject='Mathematics',
        )
        self.client.force_login(teacher)

    def test_attendance_snapshot_api_persists_exact_rate(self):
        student = Student.objects.create(
            student_id='S-API-001',
            first_name='Karen',
            last_name='Nabukeera',
            classroom=self.classroom,
        )

        response = self.client.post(
            reverse('attendancesnapshot-list'),
            {
                'student': student.id,
                'attendance_rate': 0.83,
                'date': '2025-03-20',
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            AttendanceSnapshot.objects.get(student=student).attendance_rate,
            0.83,
        )
        self.assertFalse(RiskPrediction.objects.filter(student=student).exists())

    def test_daily_attendance_can_be_corrected_and_refreshes_prediction(self):
        student = Student.objects.create(
            student_id='S-API-002',
            first_name='David',
            last_name='Okello',
            classroom=self.classroom,
        )
        path = reverse('dashboard-student', args=[student.id])
        payload = {
            'add_attendance': 'Save attendance',
            'date': '2026-02-01',
            'status': 'absent',
            'notes': 'No explanation received.',
        }

        self.client.post(path, payload)
        payload['status'] = 'present'
        payload['notes'] = 'Attendance corrected.'
        response = self.client.post(path, payload)

        self.assertRedirects(response, path)
        self.assertEqual(AttendanceRecord.objects.filter(student=student).count(), 1)
        record = AttendanceRecord.objects.get(student=student)
        self.assertEqual(record.status, AttendanceRecord.Status.PRESENT)
        self.assertEqual(record.notes, 'Attendance corrected.')
        self.assertFalse(RiskPrediction.objects.filter(student=student).exists())

    def test_attendance_rate_updates_exact_dated_snapshot(self):
        student = Student.objects.create(
            student_id='S-000',
            first_name='Amina',
            last_name='Okello',
        )
        period_end = date(2025, 3, 20)

        record_attendance_rate(student, 100, period_end)
        record_attendance_rate(student, 25, period_end)

        self.assertEqual(
            AttendanceSnapshot.objects.get(student=student, date=period_end).attendance_rate,
            0.25,
        )
        self.assertEqual(AttendanceRecord.objects.filter(student=student).count(), 0)
        self.assertEqual(compute_student_features(student)['attendance_rate'], 0.25)

    def test_manual_entry_creates_student_and_classroom(self):
        response = self.client.post(
            reverse('dashboard-import'),
            {
                'add_student': 'Add student',
                'student_id': 'S-001',
                'first_name': 'Amina',
                'last_name': 'Okello',
                'gender': 'F',
                'classroom_name': str(self.classroom.pk),
                'subject': 'Mathematics',
                'date_of_birth': '2010-04-12',
                'guardian_name': 'Grace Okello',
                'guardian_phone': '+256700000000',
                'attendance_rate': '80',
                'assessment_date': '2025-03-10',
                'test_1': '73',
                'midterm': '64',
            },
        )

        self.assertRedirects(response, reverse('dashboard-import'))
        student = Student.objects.get(student_id='S-001')
        self.assertEqual(student.classroom.name, 'S.3 Science')
        self.assertEqual(student.date_of_birth.isoformat(), '2010-04-12')
        self.assertEqual(Classroom.objects.count(), 1)
        self.assertEqual(student.assessments.count(), 2)
        self.assertEqual(student.assessments.get(title='Midterm').score, 64)
        snapshot = AttendanceSnapshot.objects.get(student=student)
        self.assertEqual(snapshot.attendance_rate, 0.8)
        self.assertEqual(AttendanceRecord.objects.filter(student=student).count(), 0)
        self.assertTrue(RiskPrediction.objects.filter(student=student).exists())

    def test_manual_entry_rejects_duplicate_student_id(self):
        Student.objects.create(
            student_id='S-001',
            first_name='Amina',
            last_name='Okello',
        )

        response = self.client.post(
            reverse('dashboard-import'),
            {
                'add_student': 'Add student',
                'student_id': 'S-001',
                'first_name': 'Another',
                'last_name': 'Student',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Student with this Student id already exists.')
        self.assertEqual(Student.objects.count(), 1)

    def test_spreadsheet_import_remains_available(self):
        upload = SimpleUploadedFile(
            'students.csv',
            b'student_id,first_name,last_name\nS-002,Brian,Nakato\n',
            content_type='text/csv',
        )

        response = self.client.post(
            reverse('dashboard-import'),
            {'file': upload},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Imported 1 rows')
        self.assertTrue(Student.objects.filter(student_id='S-002').exists())

    def test_api_import_reports_invalid_spreadsheet_as_bad_request(self):
        upload = SimpleUploadedFile(
            'invalid.csv',
            b'not_student_data\nvalue\n',
            content_type='text/csv',
        )

        response = self.client.post('/api/students/import_excel/', {'file': upload})

        self.assertEqual(response.status_code, 400)
        self.assertIn('Missing required columns', response.json()['detail'])

    def test_imported_scores_are_ordered_before_endterm_training_labels(self):
        upload = SimpleUploadedFile(
            'scores.csv',
            (
                b'student_id,first_name,last_name,endterm,endterm_date,midterm,midterm_date,test_1,test_1_date\n'
                b'S-005,James,Opio,75,2025-01-10,60,2025-01-05,80,2025-01-01\n'
            ),
            content_type='text/csv',
        )

        response = self.client.post(reverse('dashboard-import'), {'file': upload})

        self.assertEqual(response.status_code, 200)
        features, labels = build_training_frame()
        self.assertEqual(len(labels), 1)
        self.assertEqual(features.iloc[0]['avg_score'], 70)
        student = Student.objects.get(student_id='S-005')
        self.assertEqual(
            list(student.assessments.order_by('id').values_list('assessment_type', flat=True)),
            [
                Assessment.AssessmentType.TEST,
                Assessment.AssessmentType.MIDTERM,
                Assessment.AssessmentType.ENDTERM,
            ],
        )
        self.assertEqual(
            set(student.assessments.values_list('subject', flat=True)),
            {'Mathematics'},
        )

    def test_import_rejects_scores_for_unassigned_subject(self):
        upload = SimpleUploadedFile(
            'scores.csv',
            (
                b'student_id,first_name,last_name,subject,test_1\n'
                b'S-006,James,Opio,Science,80\n'
            ),
            content_type='text/csv',
        )

        response = self.client.post(reverse('dashboard-import'), {'file': upload})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'is not assigned to you')
        self.assertFalse(Student.objects.filter(student_id='S-006').exists())

    def test_excel_import_creates_students(self):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(['student_id', 'first_name', 'last_name'])
        worksheet.append(['S-003', 'Claire', 'Mugisha'])
        file_content = BytesIO()
        workbook.save(file_content)
        upload = SimpleUploadedFile(
            'students.xlsx',
            file_content.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )

        response = self.client.post(
            reverse('dashboard-import'),
            {'file': upload},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Imported 1 rows')
        self.assertTrue(Student.objects.filter(student_id='S-003').exists())

    def test_existing_student_can_receive_new_assessment(self):
        student = Student.objects.create(
            student_id='S-004',
            first_name='Daniel',
            last_name='Opio',
            classroom=self.classroom,
        )

        response = self.client.post(
            reverse('dashboard-student', args=[student.id]),
            {
                'add_assessment': 'Save assessment',
                'assessment_type': Assessment.AssessmentType.ENDTERM,
                'subject': 'Mathematics',
                'title': 'Term 1 examination',
                'score': '72',
                'max_score': '100',
                'date': '2025-11-20',
            },
        )

        self.assertRedirects(response, reverse('dashboard-student', args=[student.id]))
        self.assertEqual(student.assessments.get().score, 72)
        self.assertTrue(RiskPrediction.objects.filter(student=student).exists())
