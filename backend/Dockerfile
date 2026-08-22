FROM python:3.11-slim

# git is REQUIRED, not optional -- app/ingestion/cloner.py shells out to it
# for every analysis. Without this line, the failure shows up much later,
# deep inside the cloner, as a confusing "git: command not found" -- the
# startup check below fails fast with a clear message instead.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 compass
WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

# Fail fast and clearly if git is somehow missing/broken, instead of a
# confusing error deep inside the cloner on the first real request.
RUN git --version

USER compass

# Migrations run via Render's pre-deploy command (see render.yaml), NEVER
# here -- two instances racing `alembic upgrade head` on container boot is a
# real failure mode with a shared Postgres.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
