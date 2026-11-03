# The target's machine (scenario 4): Python with git and curl, like the mentor's
# sandbox image. No network beyond the compose networks.
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/* && pip install --no-cache-dir pytest==8.3.3
WORKDIR /workspace
CMD ["sleep", "infinity"]
