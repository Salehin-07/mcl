from django.contrib import admin
from .models import Contact, ContactRequest

# Register your models here.
admin.site.register(Contact)
admin.site.register(ContactRequest)