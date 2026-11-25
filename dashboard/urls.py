from django.urls import path

from . import admin_views, views

urlpatterns = [
    path('', views.role_dashboard, name='role-dashboard'),
    path('teacher/', views.home, name='dashboard-home'),
    path('teacher/students/<int:student_id>/', views.student_detail, name='dashboard-student'),
    path(
        'teacher/students/<int:student_id>/interventions/<int:intervention_id>/complete/',
        views.complete_intervention,
        name='dashboard-complete-intervention',
    ),
    path('teacher/run-analysis/', views.run_analysis, name='dashboard-run-analysis'),
    path(
        'teacher/alerts/<int:alert_id>/ack/',
        views.acknowledge_alert,
        name='dashboard-ack-alert',
    ),
    path('teacher/import/', views.import_page, name='dashboard-import'),
    path('reports/performance.xlsx', views.export_performance_report, name='dashboard-export-report'),
    path('school-admin/', admin_views.home, name='school-admin-home'),
    path('school-admin/students/', admin_views.students, name='school-admin-students'),
    path(
        'school-admin/students/new/',
        admin_views.student_form,
        name='school-admin-student-create',
    ),
    path(
        'school-admin/students/<int:student_id>/edit/',
        admin_views.student_form,
        name='school-admin-student-edit',
    ),
    path(
        'school-admin/students/<int:student_id>/promote/',
        admin_views.promote_student,
        name='school-admin-student-promote',
    ),
    path('school-admin/teachers/', admin_views.teachers, name='school-admin-teachers'),
    path(
        'school-admin/teachers/new/',
        admin_views.teacher_form,
        name='school-admin-teacher-create',
    ),
    path(
        'school-admin/teachers/<int:teacher_id>/assign/',
        admin_views.teacher_assign,
        name='school-admin-teacher-assign',
    ),
    path(
        'school-admin/classes/<int:classroom_id>/interventions/',
        admin_views.plan_class_intervention,
        name='school-admin-class-intervention',
    ),
]
