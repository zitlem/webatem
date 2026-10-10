from django.urls import path

from atem_control.atemstream import views

urlpatterns = [
    path('state/',  views.stream_state,  name='atemstream_state'),
    path('action/', views.stream_action, name='atemstream_action'),
]
