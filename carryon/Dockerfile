FROM python:3.12-slim

# Tailscale for optional public access via Funnel (pinned, checksum-verified).
ARG BUILD_ARCH=aarch64
ARG TAILSCALE_VERSION=1.102.3
RUN set -e; \
    case "$BUILD_ARCH" in \
      aarch64) a=arm64; sum=a0fa1b154af8c61f862a2259f559f7396d96c0225f4a863eae2333e1546bbe25 ;; \
      amd64)   a=amd64; sum=36ddd9b51be57ffc2990cf76323cfa13643bfbb1b8a969f6183fa164741cdef5 ;; \
      *) echo "unsupported arch $BUILD_ARCH"; exit 1 ;; \
    esac; \
    python -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], '/tmp/ts.tgz')" \
      "https://pkgs.tailscale.com/stable/tailscale_${TAILSCALE_VERSION}_${a}.tgz"; \
    echo "$sum  /tmp/ts.tgz" | sha256sum -c -; \
    tar -xzf /tmp/ts.tgz -C /tmp; \
    mv /tmp/tailscale_*/tailscale /tmp/tailscale_*/tailscaled /usr/local/bin/; \
    rm -rf /tmp/ts.tgz /tmp/tailscale_*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY carryon/ ./carryon/
COPY run.sh .

ENV CARRYON_DATA=/data CARRYON_INBOX=/share/carryon/inbox PYTHONUNBUFFERED=1
CMD ["sh", "/app/run.sh"]
