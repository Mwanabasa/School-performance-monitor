from django.urls import path

from . import views

urlpatterns = [
    path('', views.home, name='dashboard-home'),
    path('students/<int:student_id>/', views.student_detail, name='dashboard-student'),
    path('run-analysis/', views.run_analysis, name='dashboard-run-analysis'),
    path('alerts/<int:alert_id>/ack/', views.acknowledge_alert, name='dashboard-ack-alert'),
    path('import/', views.import_page, name='dashboard-import'),
]
