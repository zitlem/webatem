"""SuperSource box and art control (local addition).

Rides the control page's own ATEM session (``ATEMInstanceManager.
peek_connection``): no second session, and nothing in the bundled store or
the consumer changes. atemwire parses SSrc / SSBP and has the CSBP / CSSc
writes; border settings have no atemwire support and are not offered.
"""
