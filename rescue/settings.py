"""Django settings for the Rescue the Surplus prototype (demo defaults)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Demo only. Set RTS_SECRET_KEY in any shared environment.
SECRET_KEY = os.environ.get("RTS_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = os.environ.get("RTS_DEBUG", "1") == "1"
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "core",
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "rescue.urls"
WSGI_APPLICATION = "rescue.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {"timeout": 20},
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
