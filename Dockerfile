FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir pyyaml pytest flask kubernetes

# Copy all source code
COPY agent /app/agent
COPY sandbox /app/sandbox
COPY evaluation /app/evaluation
COPY security /app/security
COPY api_server.py /app/
COPY run_dynamic.py /app/

# Install kubectl for Kubernetes operations
RUN apt-get update && apt-get install -y curl && \
    curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
    chmod +x kubectl && \
    mv kubectl /usr/local/bin/ && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 agentuser && \
    chown -R agentuser:agentuser /app

# Create /tmp/code directory for code execution
RUN mkdir -p /tmp/code && chown -R agentuser:agentuser /tmp/code

USER agentuser

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV KUBERNETES_MODE=true

# Default command
CMD ["python", "/app/agent/main.py"]
