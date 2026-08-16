"""Market Big Picture Watch.

The determinism import MUST stay first and MUST stay above any import that
pulls in numpy. It sets the environment variables that fix BLAS and SIMD
dispatch, and those are only read when numpy is first imported -- one import
in the wrong order and the whole reproducibility guarantee is silently gone.
See app/determinism.py for what is being pinned and why.
"""

from . import determinism as _determinism

_determinism.apply()
# Import numpy HERE, through the negotiating wrapper, so the very first
# numpy import in the process is the one that reads the pinned settings
# and the one that can recover if a wheel refuses part of the list.
_determinism.import_numpy()
