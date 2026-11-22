from django import template

from fidele.models import NotificationUser

register = template.Library()


@register.filter
def percentage(value, total):
    try:
        value = float(value)
        total = float(total)
        if total == 0:
            return 0
        return round((value / total) * 100, 2)
    except (ValueError, ZeroDivisionError):
        return 0


@register.filter
def subtract(value, arg):
    """Soustrait arg de value"""
    return value - arg


@register.simple_tag
def unread_notifs_count(user):
    if user.is_authenticated:
        return NotificationUser.objects.filter(user=user, is_read=False).count()
    return 0


@register.simple_tag
def user_notifs(user):
    if user.is_authenticated:
        return NotificationUser.objects.filter(user=user).select_related('notification').order_by('-created_at')
    return []


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key, [])


@register.filter(name='add_class')
def add_class(field, css_class):
    return field.as_widget(attrs={"class": css_class})
