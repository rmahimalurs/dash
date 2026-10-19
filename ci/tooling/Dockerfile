FROM artifactory.cloud.cms.gov/docker/kaniko-project/executor:v1.24.0-debug AS kaniko

FROM alpine:3.20

ARG KUBECTL_VERSION=v1.34.1
ARG HELM_VERSION=v3.16.3

RUN apk add --no-cache \
      aws-cli \
      bash \
      ca-certificates \
      coreutils \
      curl \
      git \
      jq \
      openssh-client \
      tar \
      yq-go

# Not /usr/local/bin: on the Jenkins agent that path came up empty, so these
# live somewhere nothing else writes.
RUN set -eux; \
    mkdir -p /opt/tools/bin; \
    arch="$(apk --print-arch)"; \
    case "$arch" in \
      x86_64)  k8s_arch=amd64 ;; \
      aarch64) k8s_arch=arm64 ;; \
      *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /opt/tools/bin/kubectl \
      "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${k8s_arch}/kubectl"; \
    chmod +x /opt/tools/bin/kubectl; \
    curl -fsSL "https://get.helm.sh/helm-${HELM_VERSION}-linux-${k8s_arch}.tar.gz" | tar xz -C /tmp; \
    mv "/tmp/linux-${k8s_arch}/helm" /opt/tools/bin/helm; \
    chmod +x /opt/tools/bin/helm; \
    rm -rf "/tmp/linux-${k8s_arch}"

# Only the binary, and not into /kaniko: this image is itself built by kaniko,
# which runs from /kaniko/executor and cannot write over it.
COPY --from=kaniko /kaniko/executor /opt/tools/bin/kaniko-executor

# SSL_CERT_DIR is deliberately not carried over from the kaniko image: it points
# at kaniko's bundled certs, and the other tools expect the system store.
ENV PATH="/opt/tools/bin:${PATH}" \
    DOCKER_CONFIG=/kaniko/.docker/

RUN /opt/tools/bin/kubectl version --client=true \
 && /opt/tools/bin/helm version --short \
 && aws --version \
 && jq --version \
 && yq --version \
 && git --version \
 && /opt/tools/bin/kaniko-executor version

CMD ["/bin/bash"]
