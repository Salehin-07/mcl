from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('contact/', views.contact, name='contact'),
    path('about-us/', views.about_us, name='about'),
    path('terms-and-condition/', views.terms, name='terms'),
    path('privacy-policy/', views.privacy_policy, name='privacy_policy'),
]
