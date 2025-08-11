# /eden/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # Fiançailles
    path("fiancailles/", views.FiancaillesListView.as_view(), name="fiancailles-list"),
    path("fiancailles/nouveau/", views.FiancaillesCreateView.as_view(), name="fiancailles-create"),
    path("fiancailles/<int:pk>/", views.FiancaillesDetailView.as_view(), name="fiancailles-detail"),
    path("fiancailles/<int:pk>/modifier/", views.FiancaillesUpdateView.as_view(), name="fiancailles-update"),
    path("fiancailles/<int:pk>/supprimer/", views.FiancaillesDeleteView.as_view(), name="fiancailles-delete"),

    # Mariage
    path("mariages/", views.MariageListView.as_view(), name="mariage-list"),
    path("mariages/nouveau/", views.MariageCreateView.as_view(), name="mariage-create"),
    path("mariages/<int:pk>/", views.MariageDetailView.as_view(), name="mariage-detail"),
    path("mariages/<int:pk>/modifier/", views.MariageUpdateView.as_view(), name="mariage-update"),
    path("mariages/<int:pk>/supprimer/", views.MariageDeleteView.as_view(), name="mariage-delete"),
]