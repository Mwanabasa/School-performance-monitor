from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.models import Group

from .models import Classroom, Student, TeacherActivity, TeacherAssignment

SCHOOL_ADMIN_GROUP = 'School Administrator'
TEACHER_GROUP = 'Teacher'


def is_school_administrator(user):
    return user.is_authenticated and (
        user.is_superuser or user.groups.filter(name=SCHOOL_ADMIN_GROUP).exists()
    )


def is_teacher(user):
    return user.is_authenticated and user.groups.filter(name=TEACHER_GROUP).exists()


def assigned_classrooms(user):
    return Classroom.objects.filter(teacher_assignments__teacher=user).distinct()


def assigned_students(user):
    return Student.objects.filter(classroom__teacher_assignments__teacher=user).distinct()


def school_admin_required(view):
    return user_passes_test(is_school_administrator, login_url='login')(view)


def is_school_user(user):
    return is_school_administrator(user) or is_teacher(user)


def school_user_required(view):
    return user_passes_test(is_school_user, login_url='login')(view)


def get_role_group(name):
    group, _ = Group.objects.get_or_create(name=name)
    return group


def record_teacher_activity(teacher, action, details='', student=None, classroom=None):
    if not is_teacher(teacher) or is_school_administrator(teacher):
        return None
    return TeacherActivity.objects.create(
        teacher=teacher,
        action=action,
        details=details,
        student=student,
        classroom=classroom or (student.classroom if student else None),
    )


def teacher_has_classroom(user, classroom):
    return TeacherAssignment.objects.filter(teacher=user, classroom=classroom).exists()


def teacher_has_subject(user, classroom, subject):
    return TeacherAssignment.objects.filter(
        teacher=user,
        classroom=classroom,
        subject=subject,
    ).exists()


def teacher_assignments(user):
    return TeacherAssignment.objects.filter(teacher=user).select_related('classroom')
