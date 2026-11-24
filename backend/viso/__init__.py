"""Viso sandbox recognition service. No Windows sign-in integration."""

import os

# OpenBLAS preallocates ~28 MB of buffers per logical core at import. This
# workload only multiplies 128-float embeddings; image math runs on OpenCV/TFLite
# threads. One BLAS thread saves ~225 MB of commit per worker on an 8-core PC.
# Must run before numpy is imported; an explicit override is still honored.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
