FROM python:3.12-slim

# Install OS-level dependencies needed for ldap3, cryptography, and cert export
RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl-dev \
    gcc \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Build dependencies come through Artifactory rather than straight from GitHub.
# A GitHub release redirects to objects.githubusercontent.com, whose chain the
# base image's CA bundle cannot currently verify, so the download fails with
# curl 60 and the build only ever succeeded off a cached layer. Override with
# --build-arg DEPS_BASE=https://github.com to go direct.
ARG DEPS_BASE=https://artifactory.cloud.cms.gov/artifactory/github-releases-remote

# SOPS binary — used by the wildcard-cert export automation to produce the
# KMS-encrypted TLS secret (.enc.yaml) before opening a PR.
ARG SOPS_VERSION=3.10.2
RUN curl -fsSL -o /usr/local/bin/sops \
      "${DEPS_BASE}/getsops/sops/releases/download/v${SOPS_VERSION}/sops-v${SOPS_VERSION}.linux.amd64" \
    && chmod +x /usr/local/bin/sops

# pluto — detects Kubernetes APIs that a target cluster version removes. Used by
# the EKS control-plane upgrade card to scan the GitOps manifests before an upgrade.
ARG PLUTO_VERSION=5.24.4
RUN curl -fsSL -o /tmp/pluto.tar.gz \
      "${DEPS_BASE}/FairwindsOps/pluto/releases/download/v${PLUTO_VERSION}/pluto_${PLUTO_VERSION}_linux_amd64.tar.gz" \
    && tar -xzf /tmp/pluto.tar.gz -C /usr/local/bin pluto \
    && chmod +x /usr/local/bin/pluto \
    && rm /tmp/pluto.tar.gz

WORKDIR /app

# Install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ ./app/

# Bake the AD CA cert for LDAPS certificate validation (AD_LDAP_CA_FILE)
COPY certs/ ./certs/

# Create the profiles data directory
RUN mkdir -p /data/profiles

# Non-root user for security
RUN useradd --system --uid 1001 --no-create-home appuser \
    && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/dashboard/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
