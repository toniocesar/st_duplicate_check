import re

s = "549300EET58YV5QD4578"
print(re.fullmatch(r"[A-Z0-9]{20}", s))
print(repr(s))
print(len(s))
print([hex(ord(c)) for c in s])