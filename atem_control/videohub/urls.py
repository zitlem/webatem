from django.urls import path

from atem_control.videohub import views

urlpatterns = [
    path('',                  views.videohub_page,        name='videohub'),
    path('api/discovered/',   views.videohub_discovered,  name='videohub_discovered'),
    path('api/open/',         views.videohub_open,        name='videohub_open'),
    path('api/state/',        views.videohub_state,       name='videohub_state'),
    path('api/route/',        views.videohub_route,       name='videohub_route'),
    path('api/previous/',     views.videohub_previous,    name='videohub_previous'),
    path('api/lock/',         views.videohub_lock,        name='videohub_lock'),
    path('api/label/',        views.videohub_label,       name='videohub_label'),
    path('api/salvos/',       views.videohub_salvos,      name='videohub_salvos'),
    path('api/routes-file/',  views.videohub_routes_file, name='videohub_routes_file'),
    path('api/scan/',         views.videohub_scan,        name='videohub_scan'),
    path('api/release/',      views.videohub_release,     name='videohub_release'),
]
