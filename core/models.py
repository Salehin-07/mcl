from django.db import models

# Create your models here.
class Contact(models.Model):
    phone = models.CharField()
    email = models.EmailField(max_length=254)
    location = models.CharField()
    opening_hours_week = models.CharField()
    
    def __str__(self):
        return "Contact Information"

class ContactRequest(models.Model):
    email = models.EmailField(max_length=254)
    what_said = models.TextField()
    
    def __str__(self):
        return self.email

class FAQ(models.Model):
    question = models.CharField(max_length=256)
    answer = models.TextField()
    
    def __str__(self):
        return self.question