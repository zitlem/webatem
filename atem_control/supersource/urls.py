from django.urls import path

from atem_control.supersource import views

urlpatterns = [
    path('state/', views.supersource_state, name='supersource_state'),
    path('box/',   views.supersource_box,   name='supersource_box'),
    path('art/',   views.supersource_art,   name='supersource_art'),
]
