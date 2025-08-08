from django.urls import path
from .views import whatsapp_webhook, simulate_chat_flow

urlpatterns = [
    path('webhook/', whatsapp_webhook, name='whatsapp_webhook'),
    path('simulate/', simulate_chat_flow, name='simulate_chat_flow'),
]
