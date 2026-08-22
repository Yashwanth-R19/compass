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

# alembic.ini + alembic/ (env.py, versions/) are needed at RUNTIME, not just
# build time: render.yaml's dockerCommand runs `alembic upgrade head` inside
# this exact container on every deploy (see its comment for why -- free-tier
# Render doesn't support a separate pre-deploy step). Without these two
# COPY lines the image builds fine and then fails on first deploy with
# "alembic.ini not found", since nothing above installs the migration
# scripts themselves -- `pip install .` only packages `app/`.
COPY alembic.ini ./
COPY alembic ./alembic

# Fail fast and clearly if git is somehow missing/broken, instead of a
# confusing error deep inside the cloner on the first real request.
RUN git --version

USER compass

# The default CMD just serves the API -- render.yaml's dockerCommand
# overrides this to run `alembic upgrade head` first (see its comment for
# why that's safe specifically on Render's free tier). Local `docker run`
# without an override will NOT run migrations; run them yourself first via
# `alembic upgrade head` against the target database.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
