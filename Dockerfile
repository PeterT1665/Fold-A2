# Fold A2 poker room. Runs the web server with our bots (v4.2 and v3.5) and the house bots.
# Python 3.12 matches the tournament sandbox. Build from the repo root:  docker build -t fold-a2-poker .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# the SDK is vendored so the build never depends on the organisers' website
COPY play/vendor/macpoker-0.1.0-py3-none-any.whl /tmp/
RUN pip install --no-cache-dir /tmp/macpoker-0.1.0-py3-none-any.whl && rm /tmp/*.whl

COPY play ./play
COPY v4 ./v4
COPY macpoker-scaffold ./macpoker-scaffold

RUN useradd --create-home app && chown -R app /app
USER app

# hosting platforms inject PORT; override these from the platform's environment settings
ENV HOST=0.0.0.0 PORT=8000 MAX_ROOMS=40 IDLE_MINUTES=5
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','8000'), timeout=2)" || exit 1

CMD ["python", "play/server.py"]
