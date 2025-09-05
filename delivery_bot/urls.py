from django.contrib import admin
from django.urls import path, include
from chatbot.views import whatsapp_webhook


urlpatterns = [
    path('admin/', admin.site.urls),
    path('chatbot/', include('chatbot.urls')),
    path('webhook/', whatsapp_webhook, name='whatsapp_webhook'),

]
