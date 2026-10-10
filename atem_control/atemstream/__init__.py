"""Built-in streaming and recording on ATEMs that have them (local addition).

Mini Pro / Extreme / some Constellation models report StRS / SRSU / RTMS
state; switchers without the hardware report none, and the panel stays
hidden. atemwire's writes here are its "restored upstream commands", not
verified on a switcher by that fork or this one.
"""
