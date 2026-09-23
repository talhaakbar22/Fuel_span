from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("api/route/", views.route_fuel_plan, name="route_fuel_plan"),
]
