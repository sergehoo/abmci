from django.urls import path

from formation import views

urlpatterns = [
    # Catalogue
    path('',                                    views.FormationCatalogView.as_view(),  name='formations_index'),
    path('mes-inscriptions/',                   views.MesInscriptionsView.as_view(),   name='formations_mes_inscriptions'),
    path('nouveau/',                            views.FormationCreateView.as_view(),   name='formation_create'),

    # Parcours
    path('<slug:slug>/',                        views.FormationDetailView.as_view(),   name='formation_detail'),
    path('<slug:slug>/modifier/',               views.FormationUpdateView.as_view(),   name='formation_update'),

    # Sessions
    path('sessions/nouvelle/',                  views.FormationSessionCreateView.as_view(), name='formation_session_create'),
    path('sessions/<int:pk>/',                  views.FormationSessionDetailView.as_view(), name='formation_session_detail'),
    path('sessions/<int:pk>/modifier/',         views.FormationSessionUpdateView.as_view(), name='formation_session_update'),
    path('sessions/<int:pk>/supprimer/',        views.FormationSessionDeleteView.as_view(), name='formation_session_delete'),

    # Modules
    path('sessions/<int:session_pk>/modules/nouveau/',
         views.FormationModuleCreateView.as_view(), name='formation_module_create'),

    # Inscriptions
    path('sessions/<int:session_pk>/inscrire/',
         views.FormationInscrireView.as_view(), name='formation_inscrire'),

    # Présences (AJAX)
    path('sessions/<int:session_pk>/presence/toggle/',
         views.TogglePresenceView.as_view(), name='formation_presence_toggle'),
]
