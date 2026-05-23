# klight MCP Integration — Use klight with Claude and any LLM

klight ships a built-in MCP (Model Context Protocol) server. Once configured,
you can manage Kubernetes environments entirely through natural language — no
CLI flags to remember, no YAML to write.

---

## Setup — 2 minutes

### Claude Code (recommended)

```bash
claude mcp add klight -- klight mcp
```

That's it. Restart Claude Code and start talking to it.

### Claude Desktop

Edit `~/.config/claude/claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "klight": {
      "command": "klight",
      "args": ["mcp"],
      "env": {
        "KUBECONFIG": "/tmp/klight-demo-kubeconfig.yaml"
      }
    }
  }
}
```

Restart Claude Desktop.

### Any other MCP-compatible LLM

```bash
klight mcp   # starts a stdio MCP server — wire it to any MCP client
```

---

## What the LLM can do

### Tools (actions)

| Tool | What you'd say |
|------|----------------|
| `deploy_environment` | "deploy the store profile to env alice" |
| `deploy_from_repos` | "deploy ./inventory-api and ./store-api to env dev" |
| `service_status` | "what's running in env tienda?" |
| `get_logs` | "show me the last 50 lines from store-api in env alice" |
| `destroy_environment` | "tear down env alice" |
| `replace_service` | "replace store-api in env dev with my local build at ./store-api" |
| `restore_service` | "restore store-api to the CI image" |
| `get_unready` | "what's broken in env dev and how do I fix it?" |
| `init_service` | "scan ./my-service and generate a klight.yaml for it" |
| `sync_team` | "sync the team config from github.com/my-org/infra/klight-team.yaml" |
| `switch_target` | "switch to the remote cluster" |
| `run_preflight` | "check if all images are available before I deploy" |

### Resources (context — no tool call needed)

| Resource | Gives Claude |
|----------|-------------|
| `klight://cluster` | Current target, CPUs, RAM, minikube status |
| `klight://environments` | All active environments + pod status |
| `klight://team-yaml` | Current synced klight-team.yaml contents |

Claude reads these automatically before answering questions like "what
environments do I have?" — no explicit command needed.

---

## Example conversations

**Developer (World 1 — local repos):**
```
You: deploy ./inventory-api, ./store-api, and ./store-web to an env called dev
Claude: [calls deploy_from_repos] ✓ Deployed 3 services to env-dev.
        inventory-api: Running (1/1)
        store-api: Running (1/1)
        store-web: Running (1/1)

You: store-api is crashing, show me the logs
Claude: [calls get_logs] Here are the last 100 lines from store-api...
        "Connection refused to postgres:5432"
        
You: what's wrong and how do I fix it?
Claude: [calls get_unready] store-api is waiting on postgres.
        The sentinel should have blocked it — try: klight replace store-api ...
```

**Developer (World 2 — team sync):**
```
You: sync the team config and deploy the store profile for me as env alice
Claude: [calls sync_team, then deploy_environment]
        ✓ Synced klight-team.yaml (4 services, 2 profiles)
        ✓ Deploying store profile to env-alice...
        All pods ready in 45s.
```

**DevOps:**
```
You: scan our new billing-service repo at ./billing-service and generate klight.yaml
Claude: [calls init_service] Detected: FastAPI on port 8082, needs postgres.
        Generated klight.yaml:
        name: billing-service
        port: 8082
        needs: [postgres]
        health: /health
        
You: looks good, now help me add it to our klight-team.yaml
Claude: Here's the updated team.yaml with billing-service added to the
        store profile...
```

---

## Verify the server works

```bash
# Install/update klight with MCP support
cd kraken-light/klight && pip install -e .

# Test the server starts
klight mcp --help

# Inspect all tools via browser UI (no Claude needed)
npx @modelcontextprotocol/inspector klight mcp
```

The inspector opens at `http://localhost:5173` where you can call tools
interactively and inspect the resources.
