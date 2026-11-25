from rest_framework.permissions import BasePermission

from .access import is_school_administrator, is_teacher


class IsSchoolAdministrator(BasePermission):
    def has_permission(self, request, view):
        return is_school_administrator(request.user)


class IsSchoolUser(BasePermission):
    def has_permission(self, request, view):
        return is_school_administrator(request.user) or is_teacher(request.user)


class IsTeacher(BasePermission):
    def has_permission(self, request, view):
        return is_teacher(request.user) and not is_school_administrator(request.user)
