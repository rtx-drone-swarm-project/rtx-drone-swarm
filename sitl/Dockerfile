FROM python:3.12-slim

WORKDIR /workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        build-essential \
        git \
        libxml2-dev \
        libxslt1-dev \
        procps \
        python3-dev \
        rsync \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    MAVProxy \
    empy \
    future \
    pexpect \
    pyserial

COPY scripts ./scripts

CMD ["./scripts/launch_sitl.sh"]
