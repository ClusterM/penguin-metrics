# Penguin Metrics Docker Image
# Linux system telemetry for Home Assistant via MQTT

FROM python:3.13-slim

LABEL maintainer="Penguin Metrics"
LABEL description="Linux system telemetry for Home Assistant via MQTT"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Create application directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY penguin_metrics/ ./penguin_metrics/

# Create config directory
RUN mkdir -p /etc/penguin-metrics

# Default config location
ENV PENGUIN_METRICS_CONFIG=/etc/penguin-metrics/config.conf

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import socket; s=socket.socket(); s.settimeout(1); s.connect(('localhost', 1883)); s.close()" || exit 1

# Run as non-root user for security
# Note: Some metrics (smaps) require root or CAP_SYS_PTRACE
# RUN useradd -r -s /bin/false penguin
# USER penguin

# Entry point
ENTRYPOINT ["python", "-m", "penguin_metrics", "-v"]
CMD ["/etc/penguin-metrics/config.conf"]

