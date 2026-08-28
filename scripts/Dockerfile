FROM ubuntu:22.04
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc-aarch64-linux-gnu g++-aarch64-linux-gnu make \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /work
