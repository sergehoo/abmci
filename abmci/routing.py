# core/routing.py
from django.urls import re_path

from abmci.consumers import NotificationConsumer

# from abmci.consumers import NotificationConsumer

websocket_urlpatterns = [
    re_path(r"ws/notifs/$", NotificationConsumer.as_asgi()),
]