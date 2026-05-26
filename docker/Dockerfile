########################################################
# Install Apache Solr Orbit to build a Docker image    #
########################################################

#
# Stage 1: build packages and compile where needed
#
FROM python:3.12-slim AS build-stage

# hadolint ignore=DL3008
RUN apt-get -y update && \
    apt-get install -y --no-install-recommends curl git gcc pbzip2 pigz make jq && \
    apt-get -y upgrade && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build/solr-orbit
COPY . .

# There is no binary package currently available for yappi on ARM.
RUN make build && \
    if test "$(uname -m)" = aarch64; then pip wheel yappi && cp yappi-*.whl dist; fi


#
# Stage 2: create image
#
FROM python:3.12-slim AS image-stage
ENV BENCHMARK_RUNNING_IN_DOCKER=True

RUN groupadd --gid 1000 solr-orbit && \
    useradd -d /solr-orbit -m -k /dev/null -g 1000 -N -u 1000 -l -s /bin/bash benchmark

WORKDIR /solr-orbit

RUN mkdir -p /solr-orbit/.solr-orbit && \
    chown -R 1000:0 /solr-orbit/.solr-orbit

COPY --from=build-stage /build/solr-orbit/dist/*.whl ./

# hadolint ignore=DL3008
RUN set -ex; \
    apt-get -y update; \
    apt-get install -y --no-install-recommends git pbzip2; \
    apt-get -y upgrade; \
    rm -rf /var/lib/apt/lists/*; \
    pip install --no-cache-dir ./*.whl; \
    rm ./*.whl

USER 1000

ARG VERSION
ARG BUILD_DATE

LABEL org.label-schema.schema-version="1.0" \
  org.label-schema.vendor="Apache" \
  org.label-schema.name="solr-orbit" \
  org.label-schema.url="https://solr.apache.org/" \
  org.label-schema.version="$VERSION" \
  org.label-schema.license="Apache-2.0" \
  org.label-schema.description="Apache Solr Orbit — performance benchmarking tool for Apache Solr clusters" \
  org.label-schema.build-date="$BUILD_DATE" \
  org.label-schema.vcs-url="https://github.com/apache/solr-orbit" \
  org.label-schema.dockerfile="https://github.com/apache/solr-orbit/blob/main/docker/Dockerfile"

VOLUME ["/solr-orbit/.solr-orbit"]

ENTRYPOINT [ "solr-orbit" ]
