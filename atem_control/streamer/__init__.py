"""Blackmagic Web Presenter / Streaming Encoder control (local addition).

Opened from the Connect page like a Videohub. The device speaks the
Blackmagic Streaming Encoder Ethernet Protocol (v1.2, TCP 9977), which has
no library in bmdwire, so ``client`` implements the part an operator needs.
"""
