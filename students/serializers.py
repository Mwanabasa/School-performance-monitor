from rest_framework import serializers

from .models import (
    Alert,
    Assessment,
    AttendanceRecord,
    AttendanceSnapshot,
    Classroom,
    Intervention,
    RiskPrediction,
    Student,
)


class ClassroomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Classroom
        fields = '__all__'


class AssessmentSerializer(serializers.ModelSerializer):
    percentage = serializers.FloatField(read_only=True)

    class Meta:
        model = Assessment
        fields = '__all__'


class AttendanceRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttendanceRecord
        fields = '__all__'


class AttendanceSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttendanceSnapshot
        fields = '__all__'


class RiskPredictionSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.full_name', read_only=True)

    class Meta:
        model = RiskPrediction
        fields = '__all__'


class AlertSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.full_name', read_only=True)

    class Meta:
        model = Alert
        fields = '__all__'


class InterventionSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.full_name', read_only=True)
    action_display = serializers.CharField(source='get_action_display', read_only=True)

    class Meta:
        model = Intervention
        fields = '__all__'


class StudentSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    classroom_name = serializers.CharField(source='classroom.name', read_only=True, default=None)
    latest_risk = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = [
            'id',
            'student_id',
            'first_name',
            'last_name',
            'full_name',
            'gender',
            'classroom',
            'classroom_name',
            'date_of_birth',
            'guardian_name',
            'guardian_phone',
            'is_active',
            'created_at',
            'updated_at',
            'latest_risk',
        ]

    def get_latest_risk(self, obj):
        latest = obj.risk_predictions.first()
        if not latest:
            return None
        return {
            'failure_probability': latest.failure_probability,
            'risk_level': latest.risk_level,
            'average_score': latest.average_score,
            'attendance_rate': latest.attendance_rate,
            'is_declining': latest.is_declining,
            'predicted_at': latest.predicted_at,
        }


class StudentDetailSerializer(StudentSerializer):
    assessments = AssessmentSerializer(many=True, read_only=True)
    attendance_records = AttendanceRecordSerializer(many=True, read_only=True)
    interventions = InterventionSerializer(many=True, read_only=True)
    alerts = AlertSerializer(many=True, read_only=True)

    class Meta(StudentSerializer.Meta):
        fields = StudentSerializer.Meta.fields + [
            'assessments',
            'attendance_records',
            'attendance_snapshots',
            'interventions',
            'alerts',
        ]
