from django.conf import settings
from django.conf.urls.static import static
from django.urls import path

from . import views
from .views import FideleListView, permanencecreate, FideleDetailView, VieDeLEgliseListView, EngagementListView, \
    StatutSocialListView, MessagerieListView, DirectionDetailView, FideleUpdateView, SuivieFideleListView, \
    FideleDeleteView, FideleTransferView, FideleCreateView, complete_profile, profile_complete, Politique

urlpatterns = [
                  path('membres/', FideleListView.as_view(), name='membres'),
                  path('fideles/ajouter/', FideleCreateView.as_view(), name='fidele_create'),
                  path('fideles/<int:pk>/modifier/', FideleUpdateView.as_view(), name='fidele_update'),
                  path('fideles/<int:pk>/supprimer/', FideleDeleteView.as_view(), name='fidele_delete'),
                  path('fideles/<int:pk>/transferer/', FideleTransferView.as_view(), name='fidele_transfer'),

                  path('complete-profile/', complete_profile, name='complete_profile'),
                  path('profile-complete/', profile_complete, name='profile_complete'),
                  path('politique/', Politique.as_view(), name='politique'),

                  path('suivie/', SuivieFideleListView.as_view(), name='suivie'),
                  path('membre/?P<str:slug>[0-9]+/', FideleDetailView.as_view(), name='membre'),
                  path('update/?P<int:pk>[0-9]+/', FideleUpdateView.as_view(), name='update'),
                  path('<int:pk>/infos_generale/', FideleDetailView.as_view(), name='infos_generale'),
                  path('<int:pk>/vie_de_leglise/', VieDeLEgliseListView.as_view(), name='vie_de_leglise'),
                  path('<int:pk>/engagement/', EngagementListView.as_view(), name='engagement'),
                  path('<int:pk>/statut_social/', StatutSocialListView.as_view(), name='statut_social'),
                  path('<int:pk>/messagerie/', MessagerieListView.as_view(), name='messagerie'),
                  path('direction/<int:pk>', DirectionDetailView.as_view(), name='direction'),
                  path('createpermanence/<int:pk>', views.permanencecreate, name='createpermanence')
              ] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
