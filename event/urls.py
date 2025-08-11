from django.conf import settings
from django.conf.urls.static import static
from django.urls import path
from event.views import EventListView, EventCalendarView, EventDetailView

urlpatterns = [
                  path('calendrier', EventCalendarView.as_view(), name='event-calend'),
                  path('event-list', EventListView.as_view(), name='event-list'),
                  path('event/<int:pk>', EventDetailView.as_view(), name='event-detail'),
                  # path('event?download_qr_code=true', download_qr_code_pdf.views, name='event-downl'),

              ] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)