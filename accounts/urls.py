from django.contrib.auth.views import LogoutView
from django.urls import path
from . import views

urlpatterns = [
    path('signup/', views.signup, name='signup'),
    path('login/', views.user_login, name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('profile/', views.profile, name='profile'),
    path('profile/update-details/',views.profile_update_details, name='profile_update_details'),
    path('profile/update-password/', views.profile_update_password, name='profile_update_password'),
    path('profile/delete/', views.profile_delete, name='profile_delete'),
]
