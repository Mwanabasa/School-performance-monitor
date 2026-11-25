from datetime import date
from unittest.mock import patch

from django.test import TestCase, override_settings

from students.models import (
    Alert,
    Assessment,
    AttendanceSnapshot,
    Intervention,
    RiskPrediction,
    Student,
)

from .features import build_training_frame, compute_student_features
from .risk_service import classify_risk, predict_student


class HistoricalPredictionFeatureTests(TestCase):
    def test_endterm_training_examples_only_use_preceding_assessments(self):
        student = Student.objects.create(
            student_id='HIST-001',
            first_name='Esther',
            last_name='Achieng',
        )
        Assessment.objects.create(
            student=student,
            assessment_type=Assessment.AssessmentType.TEST,
            title='Term 1 test',
            score=70,
            date=date(2025, 1, 5),
        )
        Assessment.objects.create(
            student=student,
            assessment_type=Assessment.AssessmentType.ENDTERM,
            title='Term 1 final',
            score=60,
            date=date(2025, 1, 5),
        )
        Assessment.objects.create(
            student=student,
            assessment_type=Assessment.AssessmentType.TEST,
            title='Term 2 test',
            score=90,
            date=date(2025, 2, 5),
        )
        Assessment.objects.create(
            student=student,
            assessment_type=Assessment.AssessmentType.ENDTERM,
            title='Term 2 final',
            score=75,
            date=date(2025, 2, 5),
        )

        features, labels = build_training_frame()

        self.assertEqual(len(labels), 2)
        self.assertEqual(features.iloc[0]['avg_score'], 70)
        self.assertAlmostEqual(features.iloc[1]['avg_score'], 220 / 3)

    def test_current_features_include_prior_endterm_results(self):
        student = Student.objects.create(
            student_id='HIST-002',
            first_name='Francis',
            last_name='Kato',
        )
        Assessment.objects.create(
            student=student,
            assessment_type=Assessment.AssessmentType.TEST,
            title='Test',
            score=80,
            date=date(2025, 2, 1),
        )
        Assessment.objects.create(
            student=student,
            assessment_type=Assessment.AssessmentType.ENDTERM,
            title='Prior final',
            score=60,
            date=date(2025, 2, 10),
        )

        features = compute_student_features(student)

        self.assertEqual(features['avg_score'], 70)


class RiskWorkflowTests(TestCase):
    @override_settings(RISK_THRESHOLD_MEDIUM=0.31, RISK_THRESHOLD_HIGH=0.61)
    def test_risk_bands_match_dashboard_cutoffs(self):
        self.assertEqual(classify_risk(0.30), RiskPrediction.RiskLevel.LOW)
        self.assertEqual(classify_risk(0.31), RiskPrediction.RiskLevel.MEDIUM)
        self.assertEqual(classify_risk(0.60), RiskPrediction.RiskLevel.MEDIUM)
        self.assertEqual(classify_risk(0.61), RiskPrediction.RiskLevel.HIGH)

    def test_decline_requires_three_consecutive_assessment_drops(self):
        student = Student.objects.create(
            student_id='DECLINE-001',
            first_name='David',
            last_name='Okello',
        )
        for index, score in enumerate((80, 68, 55, 40), start=1):
            Assessment.objects.create(
                student=student,
                assessment_type=Assessment.AssessmentType.TEST,
                title=f'Test {index}',
                score=score,
                date=date(2026, 1, index),
            )
        self.assertTrue(compute_student_features(student)['is_declining'])

        Assessment.objects.create(
            student=student,
            assessment_type=Assessment.AssessmentType.TEST,
            title='Test 5',
            score=45,
            date=date(2026, 1, 5),
        )
        self.assertFalse(compute_student_features(student)['is_declining'])

    @patch('analytics.risk_service.risk_model.predict_proba')
    def test_student_without_assessments_is_not_assigned_a_failure_risk(self, predict):
        student = Student.objects.create(
            student_id='UNASSESSED-001',
            first_name='Amina',
            last_name='Okello',
        )

        self.assertIsNone(predict_student(student))
        self.assertFalse(RiskPrediction.objects.filter(student=student).exists())
        predict.assert_not_called()

    @override_settings(ATTENDANCE_RISK_THRESHOLD=0.65)
    @patch('analytics.risk_service.risk_model.predict_proba', return_value=0.2)
    def test_attendance_below_sixty_five_percent_generates_alert_and_action(self, _predict):
        student = Student.objects.create(
            student_id='ATTENDANCE-001',
            first_name='Sarah',
            last_name='Nabukeera',
        )
        AttendanceSnapshot.objects.create(
            student=student,
            attendance_rate=0.64,
            date=date(2026, 1, 10),
        )

        predict_student(student)

        self.assertTrue(
            Alert.objects.filter(
                student=student,
                alert_type=Alert.AlertType.ATTENDANCE,
            ).exists()
        )
        self.assertTrue(
            Intervention.objects.filter(
                student=student,
                action=Intervention.Action.ATTENDANCE_FOLLOWUP,
            ).exists()
        )
