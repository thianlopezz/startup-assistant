# The assistant in a browser terminal: ttyd serves startup-assistant over HTTP (Traefik adds TLS).
# 3.14 is the version the app is built and tested on.
FROM python:3.14-slim-trixie

# ttyd isn't packaged in Debian trixie: use the official static build, pinned by checksum.
ARG TTYD_VERSION=1.7.7
ARG TARGETARCH
ADD --checksum=sha256:8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55 \
    https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.x86_64 /tmp/ttyd.amd64
ADD --checksum=sha256:b38acadd89d1d396a0f5649aa52c539edbad07f4bc7348b27b4f4b7219dd4165 \
    https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.aarch64 /tmp/ttyd.arm64
RUN install -m 0755 /tmp/ttyd.${TARGETARCH} /usr/local/bin/ttyd && rm /tmp/ttyd.*

# Non-root user; /data is created here so the named volume starts out owned by it.
RUN useradd --create-home --uid 1000 app \
    && mkdir /data && chown app:app /data

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --disable-pip-version-check .

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

USER app
EXPOSE 7681
VOLUME /data
ENTRYPOINT ["entrypoint.sh"]
