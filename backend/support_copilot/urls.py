from django.contrib import admin
from django.urls import path
from ticket_analyzer.views import health_check, analyze_ticket

urlpatterns = [
    path('health', health_check, name='health'),
    path('analyze-ticket', analyze_ticket, name='analyze-ticket'),
]