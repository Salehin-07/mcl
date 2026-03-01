from django.db import models
from django.conf import settings

# Create your models here.

class ExtendedProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='extended_profile')
    phone = models.CharField(null=True,blank=True)