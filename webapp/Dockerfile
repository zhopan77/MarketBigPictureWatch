# Pinned base image, for the same reason requirements.txt is pinned: an
# unpinned python:3.12-slim silently becomes a different Python (and a
# different OpenBLAS) on a rebuild, and this app's numbers depend on both.
FROM python:3.12-slim

WORKDIR /srv/marketwatch
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# The reproducibility settings are applied by app/__init__.py, which runs
# before numpy is imported no matter which entry point is used -- so the
# container gets the same pinned BLAS kernel and SIMD dispatch as a bare
# install, and `python run.py selftest` prints the same hash.
EXPOSE 8000

# Persist ./data as a volume so the twice-daily update survives restarts:
#     docker run -v mwdata:/srv/marketwatch/data -p 8000:8000 marketwatch
# The scheduler runs inside this process, so no sidecar cron container is
# needed -- but the container does have to stay up for it to fire.
CMD ["python", "run.py"]
