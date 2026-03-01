import datetime

from django.conf import settings
from django.db import models
from django.utils import timezone


class Order(models.Model):
    SERVICE_TYPE_CHOICES = [
        ("ptp",  "Point to Point"),
        ("oh",   "1 Hour / As Directed"),
        ("th",   "2 Hour Hire"),
        ("fair", "From Airport"),
        ("tair", "To Airport"),
    ]

    # Owner
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="orders",
    )

    # Service type
    service_type = models.CharField(max_length=10, choices=SERVICE_TYPE_CHOICES, default="ptp")

    # Passenger
    passenger_name   = models.CharField(max_length=200)
    passenger_number = models.CharField(max_length=30)
    passenger_email  = models.EmailField()

    # Trip
    number_of_passengers = models.IntegerField(default=2)
    number_of_bags       = models.IntegerField(default=2)
    pickup_address       = models.CharField(max_length=500)
    destination_address  = models.CharField(max_length=500)
    additional_stop      = models.CharField(max_length=500, null=True, blank=True)
    flight_number        = models.CharField(max_length=20, blank=True)
    pickup_date          = models.DateField(default=datetime.date.today)
    pickup_time          = models.TimeField(default=timezone.now)

    # Vehicle
    limo_service_type   = models.CharField(max_length=50)
    baby_seat           = models.BooleanField(default=False)
    return_ride         = models.BooleanField(default=False)
    special_instruction = models.TextField(null=True, blank=True)
    vehicle_colour      = models.CharField(max_length=30, null=True, blank=True)
    wedding_ribbon      = models.CharField(max_length=30, null=True, blank=True)
    special_signboard   = models.CharField(max_length=200, blank=True)

    # Payment — paid=False until webhook/session confirms success
    total_price  = models.DecimalField(max_digits=10, decimal_places=2)
    paid         = models.BooleanField(default=False)
    # Stores stripe.checkout.Session.id (cs_...)
    stripe_payment_intent_id = models.CharField(max_length=200, blank=True)

    # Meta
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Order #{self.pk} [{self.service_type.upper()}] — {self.passenger_name} ({self.pickup_date})"

    @property
    def service_type_display(self):
        return dict(self.SERVICE_TYPE_CHOICES).get(self.service_type, self.service_type)


class Rates(models.Model):
    name = models.CharField(default='Sedan 1-5')
    max_passangers = models.IntegerField(default=5)
    max_bags = models.IntegerField(default=5)
    base_price = models.DecimalField(default=30)
    per_km_rate = models.DecimalField(default=3.50
    stop = models.DecimalField(default=15)
    th_rate = models.DecimalField(default=200)
    oh_rate = models.DecimalField(default=100)

class Discount(models.Model):
    th_discount = models.DecimalField(default=0.025)
    return_discount = models.DecimalField(default=0.05)