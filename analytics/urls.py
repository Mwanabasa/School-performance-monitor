from django.urls import path

from . import views

urlpatterns = [
    path('summary/', views.summary, name='analytics-summary'),
    path('risk-report/', views.risk_report, name='analytics-risk-report'),
    path('train/', views.train_model, name='analytics-train'),
    path('predict/', views.run_predictions, name='analytics-predict-batch'),
    path('predict/<int:student_id>/', views.predict_one, name='analytics-predict-one'),
    path('model/', views.model_status, name='analytics-model-status'),
    path('charts/', views.chart_data, name='analytics-charts'),
]
