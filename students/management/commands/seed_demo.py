"""Seed demo cohort for Bethel Parents SS (~60 learners)."""
from __future__ import annotations

import random
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from analytics.risk_service import run_batch_predictions
from students.models import Assessment, AttendanceRecord, Classroom, Student


FIRST_NAMES = [
    'Amina', 'Brian', 'Claire', 'Daniel', 'Esther', 'Francis', 'Grace', 'Hassan',
    'Irene', 'James', 'Karen', 'Leo', 'Mary', 'Nathan', 'Olive', 'Paul',
    'Queenie', 'Ruth', 'Samuel', 'Tina', 'Umar', 'Vera', 'William', 'Xena',
    'Yvonne', 'Zak', 'Abdul', 'Beatrice', 'Charles', 'Diana',
]
LAST_NAMES = [
    'Okello', 'Nakato', 'Mugisha', 'Achieng', 'Ssebunya', 'Namukasa', 'Otim',
    'Nabukeera', 'Kato', 'Nalubega', 'Wanyama', 'Akello', 'Mbabazi', 'Opio',
]


class Command(BaseCommand):
    help = 'Seed ~60 demo students with assessments, attendance, then run risk analysis.'

    def add_arguments(self, parser):
        parser.add_argument('--students', type=int, default=60)
        parser.add_argument('--clear', action='store_true', help='Clear existing student data first')

    @transaction.atomic
    def handle(self, *args, **options):
        if options['clear']:
            Student.objects.all().delete()
            Classroom.objects.all().delete()
            self.stdout.write('Cleared existing students/classrooms.')

        classroom, _ = Classroom.objects.get_or_create(
            name='S.3 Science',
            defaults={
                'academic_year': '2025',
                'term': 'Term 1',
                'subject': 'Mathematics',
            },
        )

        rng = random.Random(42)
        count = options['students']
        base_date = date(2025, 2, 3)

        for i in range(1, count + 1):
            first = FIRST_NAMES[(i - 1) % len(FIRST_NAMES)]
            last = LAST_NAMES[(i - 1) % len(LAST_NAMES)]
            student, created = Student.objects.get_or_create(
                student_id=f'BPS-{i:03d}',
                defaults={
                    'first_name': first,
                    'last_name': last,
                    'gender': rng.choice(['M', 'F']),
                    'classroom': classroom,
                    'guardian_name': f'Guardian of {first}',
                    'guardian_phone': f'+2567{rng.randint(10000000, 99999999)}',
                },
            )
            if not created:
                continue

            # Ability profile: mix of strong, average, struggling
            profile = rng.choices(['strong', 'average', 'struggling', 'declining'], weights=[35, 35, 18, 12])[0]
            if profile == 'strong':
                mean, decline = 78, 0
            elif profile == 'average':
                mean, decline = 62, rng.uniform(-0.5, 0.5)
            elif profile == 'struggling':
                mean, decline = 38, rng.uniform(-0.2, 0.8)
            else:
                mean, decline = 70, -8

            schedule = [
                (Assessment.AssessmentType.TEST, 'Test 1', 0),
                (Assessment.AssessmentType.ASSIGNMENT, 'Assignment 1', 7),
                (Assessment.AssessmentType.TEST, 'Test 2', 14),
                (Assessment.AssessmentType.PROJECT, 'Project 1', 21),
                (Assessment.AssessmentType.ASSIGNMENT, 'Assignment 2', 28),
                (Assessment.AssessmentType.MIDTERM, 'Midterm Exam', 35),
                (Assessment.AssessmentType.TEST, 'Test 3', 42),
            ]

            for idx, (atype, title, day_offset) in enumerate(schedule):
                score = mean + decline * idx + rng.uniform(-6, 6)
                score = max(5, min(98, score))
                Assessment.objects.create(
                    student=student,
                    assessment_type=atype,
                    title=title,
                    score=round(score, 1),
                    date=base_date + timedelta(days=day_offset),
                )

            # Historical end-of-term for supervised training (~half the cohort)
            if i % 2 == 0:
                final = mean + decline * 7 + rng.uniform(-5, 5)
                final = max(8, min(96, final))
                Assessment.objects.create(
                    student=student,
                    assessment_type=Assessment.AssessmentType.ENDTERM,
                    title='End of Term Exam',
                    score=round(final, 1),
                    date=base_date + timedelta(days=70),
                )

            attendance_mean = {
                'strong': 0.94,
                'average': 0.82,
                'struggling': 0.62,
                'declining': 0.7,
            }[profile]
            for day in range(20):
                present = rng.random() < attendance_mean
                AttendanceRecord.objects.create(
                    student=student,
                    date=base_date + timedelta(days=day),
                    status=(
                        AttendanceRecord.Status.PRESENT
                        if present
                        else AttendanceRecord.Status.ABSENT
                    ),
                )

        self.stdout.write(self.style.SUCCESS(f'Seeded up to {count} students.'))
        summary = run_batch_predictions(retrain=True)
        self.stdout.write(self.style.SUCCESS(f"Analysis complete: {summary}"))
