from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from api.views import VerifyEmailView, UserDetailView, FideleDetailView, FideleListView, ProfileCompletionView, \
    FideleCreateView, ParticipationListCreateView, ScanQRCodeAPIView, VerseDuJourView, UpcomingEventsView, \
    UpcomingEventsHomeView, PrayerCategoryViewSet, PrayerRequestViewSet, PrayerCommentViewSet, DeviceViewSet, \
    NotificationViewSet, BibleVersionViewSet, BibleVerseViewSet, BibleTagViewSet, BannerListView, CategoryListView, \
    CreateIntentView, PaystackWebhookView, DonationVerifyAPIView, EgliseListView, EgliseDetailView, \
    EgliseProcheListView, eglises_avec_verset_du_jour, paystack_return_view, PasswordResetConfirmRedirectView
from event.views import FirebaseLoginView

router = DefaultRouter()
router.register(r'prayer-categories', PrayerCategoryViewSet, basename='prayer-category')
router.register(r'prayer-requests', PrayerRequestViewSet, basename='prayerrequest')
router.register(r'prayer-comments', PrayerCommentViewSet, basename='prayer-comment')
router.register(r'devices', DeviceViewSet, basename='devices')
router.register("versions", BibleVersionViewSet, basename="bible-version")
router.register("verses", BibleVerseViewSet, basename="bible-verse")
router.register(r'bible/tags', BibleTagViewSet, basename='bible-tag')
router.register(r"notifications", NotificationViewSet, basename="notifications")


urlpatterns = [
    path('', include(router.urls)),
    path('auth/', include('dj_rest_auth.urls')),
    path('auth/firebase/', FirebaseLoginView.as_view(), name='firebase-login'),
    path('auth/registration/', include('dj_rest_auth.registration.urls')),
    path('auth/verify-email/<str:key>/', VerifyEmailView.as_view(), name='verify_email'),
    path("auth/password/reset/confirm/<uidb64>/<token>/", PasswordResetConfirmRedirectView.as_view(),  name="password_reset_confirm"),

    path('eglises/', EgliseListView.as_view(), name='eglise-list'),
    path('eglises/<int:pk>/', EgliseDetailView.as_view(), name='eglise-detail'),
    path('eglises/proches/', EgliseProcheListView.as_view(), name='eglise-proches'),
    path('api/eglises/avec-verset/', eglises_avec_verset_du_jour, name='eglise-avec-verset'),

    path('donations/categories/', CategoryListView.as_view()),
    path('donations/intents/', CreateIntentView.as_view()),
    path('paystack/webhook/', PaystackWebhookView.as_view()),
    path('donations/verify/<str:reference>/', DonationVerifyAPIView.as_view(), name='donation-verify'),
    path("donations/thanks/", paystack_return_view, name="donations-thanks"),

    path("banners/", BannerListView.as_view(), name="banner-list"),

    path('user/', UserDetailView.as_view(), name='user-detail'),

    path('fideles/', FideleListView.as_view(), name='fidele-list'),
    path('fideles/<int:pk>/', FideleDetailView.as_view(), name='fidele-detail'),
    path('fideles/create/', FideleCreateView.as_view(), name='fidele-create'),

    path('profile-completion/', ProfileCompletionView.as_view(), name='profile-completion'),

    path('participations/', ParticipationListCreateView.as_view(), name='participation-list-create'),
    path('scan-qr/<str:event_code>/', ScanQRCodeAPIView.as_view(), name='scan-qr-code'),

    path('eglise/verse-du-jour/', VerseDuJourView.as_view(), name='verse-du-jour'),
    path("events/upcoming/", UpcomingEventsView.as_view(), name="events-upcoming"),
    path("events/home/", UpcomingEventsHomeView.as_view(), name="events-home"),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

