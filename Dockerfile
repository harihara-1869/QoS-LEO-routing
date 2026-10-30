# Linux environment for the Phase 2 packet backend.
# The pinned ns-3 package only publishes x86_64 Linux wheels, so the image is
# built for linux/amd64 even on Apple Silicon hosts (Docker emulates it).
FROM --platform=linux/amd64 ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      ca-certificates \
      git \
      python3 \
      python3-dev \
      python3-venv \
 && rm -rf /var/lib/apt/lists/*

# Keep the orbital and ns-3 environments separate, as in the native instructions.
RUN python3 -m venv /opt/leo-venv \
 && python3 -m venv /opt/leo-ns3-venv \
 && /opt/leo-venv/bin/pip install --upgrade pip \
 && /opt/leo-ns3-venv/bin/pip install --upgrade pip

# The repository is mounted at /workspace at run time, not copied into the image.
COPY requirements.txt requirements-ns3.txt /tmp/
RUN /opt/leo-venv/bin/pip install -r /tmp/requirements.txt \
 && /opt/leo-ns3-venv/bin/pip install -r /tmp/requirements-ns3.txt

# packet_backend/build.py reads this when choosing its ns-3 environment.
ENV LEO_NS3_PYTHON=/opt/leo-ns3-venv/bin/python \
    PATH=/opt/leo-venv/bin:$PATH

# The mounted repository is normally owned by the host user.
RUN git config --system --add safe.directory /workspace

WORKDIR /workspace
CMD ["/bin/bash"]
