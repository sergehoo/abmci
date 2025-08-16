# core/utils/notifications.py
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.conf import settings


def send_realtime_notification(user_id, data: dict):
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"user_{user_id}",
        {
            "type": "send_notification",
            "content": data
        }
    )

def send_fcm_multicast(tokens, title='', body='', data=None):
    if not tokens: return
    headers = {
        'Authorization': f'key={settings.FCM_SERVER_KEY}',
        'Content-Type': 'application/json',
    }
    payload = {
        'registration_ids': tokens,
        'notification': {'title': title, 'body': body},
        'data': data or {},
        'android': {'priority': 'high'},
        'apns': {'headers': {'apns-priority': '10'}},
    }
