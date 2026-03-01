from django.urls import path
from . import views
#app_name = 'orders'
urlpatterns = [
    path('', views.orders, name='orders'),
    path("status/<int:order_id>/",  views.order_status,  name="status"),
    path("stripe/webhook/",         views.stripe_webhook, name="stripe_webhook"),

]
