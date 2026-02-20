from django.db import models
from django.utils import timezone
import datetime


# Create your models here.
class Order(models.Model):
    passenger_name = models.CharField()
    passenger_number = models.CharField()
    passenger_email = models.EmailField()
    number_of_passengers = models.IntegerField(default=2)
    number_of_bags = models.IntegerField(default=2)
    pickup_address = models.CharField()
    additional_stop = models.CharField(null=True, blank=True)
    flight_number = models.CharField()
    pickup_date = models.DateField(default=datetime.date.today)
    pickup_time = models.TimeField(default=timezone.now)
    destination_address = models.CharField()
    limo_service_type = models.CharField()
    baby_seat = models.BooleanField(default=False)
    return_ride = models.BooleanField(default=False)
    special_instruction = models.TextField(null=True, blank=True)
    vehicle_colour = models.CharField(null=True, blank=True)
    wedding_ribbon = models.CharField(null=True, blank=True)
    special_signboard = models.CharField()
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    name_on_card = models.CharField()
    card_type = models.CharField()
    card_number = models.CharField()
    #booking_date = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)