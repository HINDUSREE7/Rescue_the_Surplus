from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("api/meta", views.meta),
    path("api/orgs", views.orgs),
    path("api/view", views.view),
    path("api/impact", views.impact),
    path("api/stream", views.stream),
    path("api/listings", views.create_listing),
    path("api/listings/last", views.last_listing),
    path("api/ingest", views.ingest),
    path("api/ingest/answer", views.ingest_answer),
    path("api/ingest/confirm", views.ingest_confirm),
    path("api/ingest/cancel", views.ingest_cancel),
    path("api/listings/<int:listing_id>/claim", views.claim),
    path("api/listings/<int:listing_id>/decline", views.decline),
    path("api/listings/<int:listing_id>/collect", views.collect),
    path("api/listings/<int:listing_id>/deliver", views.deliver),
    path("api/demo/reset", views.demo_reset),
    path("api/demo/speed", views.demo_speed),
    path("api/demo/scenario", views.demo_scenario),
]
