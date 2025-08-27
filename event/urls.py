from django.conf import settings
from django.conf.urls.static import static
from django.urls import path

from event import views
from event.views import EventListView, EventCalendarView, EventDetailView

urlpatterns = [
                  path('calendrier', EventCalendarView.as_view(), name='event-calend'),
                  path('event-list', EventListView.as_view(), name='event-list'),
                  path('event/<int:pk>', EventDetailView.as_view(), name='event-detail'),
                  path('evenement/creer/', views.EvenementCreateView.as_view(), name='evenement_create'),
                  path('evenement/<int:pk>/modifier/', views.EvenementUpdateView.as_view(), name='evenement_update'),
                  path('evenement/<int:pk>/supprimer/', views.EvenementDeleteView.as_view(), name='evenement_delete'),
                  path('evenement/<int:pk>/occurrences/', views.EvenementOccurrencesView.as_view(),
                       name='evenement_occurrences'),
                  # path('event?download_qr_code=true', download_qr_code_pdf.views, name='event-downl'),

              ] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)