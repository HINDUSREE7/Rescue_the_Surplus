from django.db import models


class Org(models.Model):
    ROLES = [
        ("donor", "Donor"),
        ("receiver", "Receiver"),
        ("volunteer", "Volunteer"),
        ("sponsor", "Sponsor"),
    ]
    role = models.CharField(max_length=10, choices=ROLES)
    name = models.CharField(max_length=120)
    lat = models.FloatField()
    lng = models.FloatField()
    capacity = models.FloatField(default=0)  # kg
    need = models.FloatField(default=0.5)  # 0..1, declared
    last_served = models.DateTimeField(null=True, blank=True)
    no_shows = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.name} ({self.role})"


class Listing(models.Model):
    POSTED, CLAIMED, COLLECTED, DELIVERED, EXPIRED = (
        "posted", "claimed", "collected", "delivered", "expired",
    )
    STATUS = [
        (POSTED, "Posted"),
        (CLAIMED, "Claimed"),
        (COLLECTED, "Collected"),
        (DELIVERED, "Delivered"),
        (EXPIRED, "Expired"),
    ]
    SOURCES = [("form", "Form"), ("chat", "Chat"), ("voice", "Voice")]

    donor = models.ForeignKey(Org, on_delete=models.CASCADE, related_name="posted")
    category = models.CharField(max_length=32)
    kg = models.FloatField()
    allergens = models.JSONField(default=list)  # ["none"] = explicitly declared none
    created = models.DateTimeField(db_index=True)
    expires = models.DateTimeField(db_index=True)  # safe-window end, engine-owned
    pickup_by = models.DateTimeField()  # min(donor deadline, expires - margin)
    status = models.CharField(max_length=12, choices=STATUS, default=POSTED, db_index=True)
    tier = models.IntegerField(default=-1)
    receiver = models.ForeignKey(
        Org, null=True, blank=True, on_delete=models.SET_NULL, related_name="received"
    )
    volunteer = models.ForeignKey(
        Org, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned"
    )
    pickup_otp = models.CharField(max_length=4, blank=True, default="")
    drop_otp = models.CharField(max_length=4, blank=True, default="")
    pickup_attempts = models.PositiveSmallIntegerField(default=0)
    drop_attempts = models.PositiveSmallIntegerField(default=0)
    claimed_at = models.DateTimeField(null=True, blank=True)
    otp_issued_at = models.DateTimeField(null=True, blank=True)

    collected_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=8, choices=SOURCES, default="form")

    class Meta:
        ordering = ["-created", "-id"]

    def __str__(self):
        return f"Listing #{self.id} {self.category} ({self.kg:g}kg, {self.status})"


class Offer(models.Model):
    STATUS = [
        ("pending", "Pending"),
        ("accepted", "Accepted"),
        ("declined", "Declined"),
        ("expired", "Expired"),
    ]
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="offers")
    receiver = models.ForeignKey(Org, on_delete=models.CASCADE, related_name="offers")
    score = models.FloatField()
    parts = models.JSONField(default=dict)  # {components, weights} at offer time
    eta = models.FloatField()  # minutes
    tier = models.IntegerField()
    status = models.CharField(max_length=10, choices=STATUS, default="pending")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["listing", "receiver"], name="unique_offer")
        ]

    def __str__(self):
        return f"Offer #{self.id} for Listing #{self.listing_id} to {self.receiver.name} ({self.status})"


class Event(models.Model):
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="events")
    at = models.DateTimeField()
    text = models.CharField(max_length=300)

    class Meta:
        ordering = ["at", "id"]

    def __str__(self):
        return f"Event #{self.id} for Listing #{self.listing_id} at {self.at}: {self.text[:30]}"


class Draft(models.Model):
    STATUS = [
        ("open", "Open"),
        ("confirmed", "Confirmed"),
        ("cancelled", "Cancelled"),
        ("expired", "Expired"),
    ]
    org = models.ForeignKey(Org, on_delete=models.CASCADE, related_name="drafts")
    raw_text = models.TextField()
    lang = models.CharField(max_length=4, default="en")
    channel = models.CharField(max_length=8, default="chat")
    parsed = models.JSONField(default=dict)  # category, kg, pickup_in_min, allergens, ready_by
    field_sources = models.JSONField(default=dict)  # field -> llm|rules|both|donor
    confidence = models.JSONField(default=dict)  # field -> high|medium|low|missing
    missing = models.JSONField(default=list)
    asked = models.CharField(max_length=20, blank=True, default="")
    clarify_count = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=12, choices=STATUS, default="open", db_index=True)
    idempotency_key = models.CharField(max_length=64, blank=True, default="")
    listing = models.ForeignKey(
        Listing, null=True, blank=True, on_delete=models.SET_NULL, related_name="drafts"
    )
    created = models.DateTimeField(db_index=True)

    def __str__(self):
        return f"Draft #{self.id} ({self.org.name}, {self.status})"
