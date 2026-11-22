import logging
import os
import sys
import threading
import time

from django.apps import AppConfig

log = logging.getLogger(__name__)


def _ticker():
    """Demo clock: run engine.tick() every 2 s. Production uses Celery beat."""
    from django.db import close_old_connections

    from . import engine

    while True:
        try:
            engine.tick()
        except Exception:  # keep the demo ticker alive
            log.exception("tick failed")
        finally:
            close_old_connections()
        time.sleep(2)


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        serving = "runserver" in sys.argv and (
            os.environ.get("RUN_MAIN") == "true" or "--noreload" in sys.argv
        )
        if serving:
            threading.Thread(target=_ticker, daemon=True, name="rts-ticker").start()
