"""Blackmagic Videohub router control (local addition).

A Videohub is opened from the Connect page instead of an ATEM, on its own
page (``/atem/videohub/?ip=``). The protocol client is ``videohubwire`` from
the bmdwire distribution, extended in ``client`` with what the operator
surface needs and the library leaves out: output locks, multi-crosspoint
routing (salvos) and the hub's per-output take mode.
"""
