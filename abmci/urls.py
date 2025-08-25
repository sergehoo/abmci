"""
URL configuration for abmci project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
import notifications
from allauth.account.views import SignupView, LoginView, LogoutView
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.template.defaulttags import url
from django.urls import path, include
from django.views.generic import TemplateView

from api.views import schema_view, AccountDeletePerformWebhook
from fidele.views import HomePageView, FideleListView, mark_all_read, mark_read, all_notifications, \
    AccountDeleteRequestView, AccountDeleteDoneView

urlpatterns = [
                  path('admin/', admin.site.urls),
                  path('api/', include('api.urls')),
                  path('accounts/', include('allauth.urls')),
                  path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),

                  # path('notifs/', include(notifs_urls)),
                  path('notify', all_notifications, name='all'),
                  path('read/<int:pk>/', mark_read, name='mark_read'),
                  path('read/all/', mark_all_read, name='mark_all_read'),
                  path("app/reset-password",
                            TemplateView.as_view(template_name="app/reset_password.html"),
                            name="app-reset-password",
                        ),

                  path('fidele/', include('fidele.urls')),
                  path('evenements/', include('event.urls')),
                  path('eden/', include('eden.urls')),
                  path('', HomePageView.as_view(), name='home'),
                  path('signup/', SignupView.as_view(template_name='registration/signup.html'), name='account_signup'),
                  path('login/', LoginView.as_view(template_name='registration/login.html'), name='account_login'),
                  path('logout/', LogoutView.as_view(template_name='registration/logout.html'), name='account_logout'),
                  path("account/delete/", AccountDeleteRequestView.as_view(), name="account_delete"),
                  path("account/delete/done/", AccountDeleteDoneView.as_view(), name="account_delete_done"),
                  # API (pour app mobile) : POST auth → crée la demande de suppression
                  path("api/account/delete/", AccountDeletePerformWebhook.as_view(), name="api_account_delete"),
              ] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
