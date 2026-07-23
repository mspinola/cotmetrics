import os

# Prevent any boot-time options fetch (live network I/O) during test collection.
os.environ.setdefault("COT_SKIP_BOOT_FETCH", "1")
