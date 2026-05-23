# Apache Solr Orbit Docker Image

This Docker image provides a container with all dependencies pre-installed so you can run [Apache Solr Orbit](https://github.com/apache/solr-orbit) without a local Python setup.

**Prerequisite:** [Docker Desktop](https://docs.docker.com/get-docker/) or [Docker Engine](https://docs.docker.com/engine/install/) must be installed.

## Running the Image

```bash
docker run apache/solr-orbit [ARGS]
```

For example, passing `-h` prints the help text. The container exits automatically when the process finishes.

To run interactively:

```bash
docker run --entrypoint bash -it apache/solr-orbit -c /bin/bash
```

This drops you into a shell inside the container where you can invoke `solr-orbit` with any subcommand or option. Exit the shell to terminate the container.

## Building a Local Image

1. Clone the repository:
   ```bash
   git clone https://github.com/apache/solr-orbit.git
   cd solr-orbit
   ```

2. Make any local changes.

3. Build the image:
   ```bash
   docker build --build-arg VERSION=<version> -t solr-orbit:<tag> -f docker/Dockerfile .
   ```

   The `VERSION` build argument is embedded in the image labels. You can set it to any string that identifies your build (e.g. `dev` or a semantic version).

## Dockerfile Best Practices

Follow the [Dockerfile best practices guide](https://docs.docker.com/develop/develop-images/dockerfile_best-practices/) when modifying the `Dockerfile`.
