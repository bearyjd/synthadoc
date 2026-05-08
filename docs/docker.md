# Docker Deployment Guide

Synthadoc ships as a multi-arch Docker image (linux/amd64, linux/arm64) published
to the GitHub Container Registry on every push to `main` and on every version tag.

---

## Image tags

| Tag | When published | Description |
|-----|---------------|-------------|
| `latest` | On `v*.*.*` tags | Latest stable release |
| `edge` | Every push to `main` | Bleeding-edge from main branch |
| `vX.Y.Z` | On `v*.*.*` tags | Exact version pin |
| `vX.Y` | On `v*.*.*` tags | Minor-version pin |
| `vX` | On `v*.*.*` tags | Major-version pin |
| `pr-NNN` | On pull requests | PR build (not pushed to registry) |
| `*-vectors` | Same cadence | All above, with fastembed vector search |

Pull the base image:

```bash
docker pull ghcr.io/axoviq-ai/synthadoc:latest
```

Pull the vectors variant (requires more disk; includes Rust-built fastembed):

```bash
docker pull ghcr.io/axoviq-ai/synthadoc:latest-vectors
```

---

## Quick start with Docker Compose

```bash
# 1. Copy the example env file and fill in at least one LLM key
cp .env.example .env
$EDITOR .env

# 2. Start
docker compose up -d

# 3. Tail logs
docker compose logs -f

# 4. Open the wiki
open http://localhost:7070
```

The first run will initialise a fresh wiki under the `/wikis` volume, then start
the HTTP + MCP server. Subsequent restarts reuse the existing wiki.

---

## docker run one-liner

```bash
docker run -d \
  --name synthadoc \
  -p 7070:7070 \
  -v synthadoc-wikis:/wikis \
  -e WIKI_NAME=main \
  -e WIKI_DOMAIN="My knowledge base" \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  --restart unless-stopped \
  ghcr.io/axoviq-ai/synthadoc:latest
```

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WIKI_NAME` | `main` | Wiki identifier; maps to `/wikis/<WIKI_NAME>` |
| `WIKI_DOMAIN` | `Personal knowledge base` | Domain hint used when scaffolding a new wiki |
| `WIKI_PORT` | `7070` | Port the server listens on inside the container |
| `SYNTHADOC_PROVIDER` | _(config.toml default)_ | Override the LLM provider for this session. Use `claude-code` to route through a local Claude Code session with no API key. Other options: `anthropic`, `openai`, `groq`. |
| `ANTHROPIC_API_KEY` | _(none)_ | Anthropic provider key |
| `OPENAI_API_KEY` | _(none)_ | OpenAI provider key |
| `GEMINI_API_KEY` | _(none)_ | Google Gemini provider key |
| `GROQ_API_KEY` | _(none)_ | Groq provider key |
| `TAVILY_API_KEY` | _(none)_ | Enables web-search ingestion |

At least one LLM key is required unless `SYNTHADOC_PROVIDER=claude-code` is set,
which routes all LLM calls through a local Claude Code session and needs no API key.

---

## Persistent volume

Wikis are stored under `/wikis` inside the container. The Compose file creates a
named Docker volume (`synthadoc-wikis`) by default, which persists across container
restarts and upgrades.

### Bind-mount to a host path (e.g. NAS)

Replace the volume block in `docker-compose.yml`:

```yaml
volumes:
  - /mnt/nas/synthadoc/wikis:/wikis
```

Ensure the host path is writable by UID 1001 (the `synthadoc` user inside the
container).

With **rootless Podman** (no sudo required):
```bash
podman unshare chown 1001:1001 /mnt/nas/synthadoc/wikis
```

With **Docker / rootful Podman**:
```bash
sudo chown -R 1001:1001 /mnt/nas/synthadoc/wikis
```

---

## Multi-wiki pattern

Run two independent wikis on different ports, sharing the same volume:

```yaml
services:
  wiki-personal:
    image: ghcr.io/axoviq-ai/synthadoc:latest
    ports: ["7070:7070"]
    volumes: [synthadoc-wikis:/wikis]
    environment:
      WIKI_NAME: personal
      WIKI_DOMAIN: Personal notes
      WIKI_PORT: "7070"
      ANTHROPIC_API_KEY: "${ANTHROPIC_API_KEY}"

  wiki-work:
    image: ghcr.io/axoviq-ai/synthadoc:latest
    ports: ["7071:7071"]
    volumes: [synthadoc-wikis:/wikis]
    environment:
      WIKI_NAME: work
      WIKI_DOMAIN: Work projects
      WIKI_PORT: "7071"
      ANTHROPIC_API_KEY: "${ANTHROPIC_API_KEY}"

volumes:
  synthadoc-wikis:
```

Both wikis live under the same `/wikis` volume at `/wikis/personal` and
`/wikis/work` respectively.

---

## Building locally

```bash
# Base image (no vector search)
docker build --target base -t synthadoc:local .

# Vectors image (requires Rust toolchain; longer build)
docker build --target vectors -t synthadoc:local-vectors .

# Custom Python version
docker build --build-arg PYTHON_VERSION=3.12 --target base -t synthadoc:py312 .
```

To use your local build instead of the registry image, uncomment the `build:`
block in `docker-compose.yml` and comment out the `image:` line.

---

## CLI usage via docker exec

While the container is running you can invoke the CLI directly:

```bash
# List wikis
docker exec synthadoc synthadoc list

# Ingest a URL into the running wiki
docker exec synthadoc synthadoc ingest https://example.com -w main

# Open an interactive shell
docker exec -it synthadoc bash
```

---

## MCP server connection

Synthadoc exposes an MCP endpoint alongside the HTTP server. Point your MCP
client at the container:

```bash
# In your MCP client config
SYNTHADOC_URL=http://localhost:7070
```

Or when running with Compose and an MCP client on the same host:

```bash
SYNTHADOC_URL=http://localhost:7070 your-mcp-client
```

---

## Tailscale reverse proxy

To expose Synthadoc on your Tailnet without opening a public port:

```bash
# On the host running the container
tailscale serve --bg http://localhost:7070
```

Then access your wiki at `https://<machine-name>.<tailnet>.ts.net` from any
device on your Tailnet.

---

## GHCR package page

Once published upstream, the image will be available at:

```
https://github.com/axoviq-ai/synthadoc/pkgs/container/synthadoc
```
