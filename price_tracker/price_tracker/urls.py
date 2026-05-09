from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static

from tracker.views import email_login_view, register_view, logout_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("tracker.urls")),
    path("login/", email_login_view, name="login"),
    path("register/", register_view, name="register"),
    path("logout/", logout_view, name="logout"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)