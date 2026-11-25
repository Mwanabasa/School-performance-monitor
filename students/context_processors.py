from .access import is_school_administrator, is_teacher


def user_roles(request):
    user = request.user
    return {
        'is_school_administrator': is_school_administrator(user),
        'is_teacher': is_teacher(user),
    }
