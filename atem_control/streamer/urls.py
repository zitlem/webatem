from django.urls import path

from atem_control.streamer import views

urlpatterns = [
    path('',                views.streamer_page,       name='streamer'),
    path('api/discovered/', views.streamer_discovered, name='streamer_discovered'),
    path('api/open/',       views.streamer_open,       name='streamer_open'),
    path('api/state/',      views.streamer_state,      name='streamer_state'),
    path('api/stream/',     views.streamer_stream,     name='streamer_stream'),
    path('api/settings/',   views.streamer_settings,   name='streamer_settings'),
    path('api/reboot/',     views.streamer_reboot,     name='streamer_reboot'),
    path('api/scan/',         views.streamer_scan,        name='streamer_scan'),
    path('api/release/',    views.streamer_release,    name='streamer_release'),
]
