# klight MCP Integration — Use klight with Claude and any LLM

klight ships a built-in MCP (Model Context Protocol) server. Add it to Claude
once and manage K8s environments in plain English — every workflow, every world.

---

## Setup

### Claude Code (30 seconds)

```bash
claude mcp add klight -- klight mcp
```

Restart Claude Code. Done.

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

Restart Claude Desktop. Done.

### Any MCP-compatible client

```bash
klight mcp   # starts a stdio MCP server
```

---

## What the LLM can do (17 tools)

### World 1 — Local cluster

| Say this | Tool called |
|----------|------------|
| "set up a local cluster with 4 CPUs and 6GB RAM" | `local_setup(cpus=4, memory=6144)` |
| "preload postgres and kafka into minikube" | `preload_infra(only="postgres,kafka")` |
| "build and load inventory-api from ./inventory-api" | `local_build_load(service, repo_path)` |
| "deploy ./inventory-api and ./store-api as env dev" | `deploy_from_repos(paths, env_name)` |

### World 2 / World 3 — Team sync + remote

| Say this | Tool called |
|----------|------------|
| "sync the team config from github.com/org/infra/..." | `sync_team(url)` |
| "deploy the store profile as env alice" | `deploy_environment(profile, env_name)` |
| "set up our EKS cluster for klight" | `setup_remote_cluster()` |
| "connect to our cluster at k8s.company.com with this token" | `connect_remote(url, token)` |
| "switch to the remote cluster" | `switch_target("remote")` |

### Observe & operate

| Say this | Tool called |
|----------|------------|
| "what's running in env alice?" | `service_status(env_name)` |
| "show last 50 lines from store-api in env dev" | `get_logs(service, env_name, tail=50)` |
| "what's broken in env alice and how do I fix it?" | `get_unready(env_name)` |
| "replace store-api in env dev with my local build" | `replace_service(service, env_name, path)` |
| "restore store-api to CI image" | `restore_service(service, env_name)` |
| "destroy env alice" | `destroy_environment(env_name)` |
| "scan ./billing-service and generate klight.yaml" | `init_service(repo_path)` |

### Resources (Claude reads automatically, no tool call needed)

| Resource | Content |
|----------|---------|
| `klight://cluster` | Active target, CPUs/RAM, minikube status |
| `klight://environments` | All active envs + pod status |
| `klight://team-yaml` | Current cached klight-team.yaml |
| `klight://capabilities` | Full map of MCP tools, CLI-only, and UI features |

---

## What requires the CLI

These commands are interactive or stream output — the LLM will give you the
exact command to run in a terminal:

```bash
klight watch <service> --env <name> --path <dir>   # hot reload on file save
klight exec  <service> --env <name>                # shell into a pod
klight open  <service> --env <name>                # port-forward + browser
klight logs  <service> --env <name> -f             # stream logs live
```

## What works better in the UI

Run `klight ui` (opens http://localhost:7700) for:

- **Live streaming logs** — auto-refresh per service
- **Cluster resize** — visual dialog with sizing estimate
- **Setup Wizard** — scan GitHub org → generate klight.yaml files → generate klight-team.yaml

---

## Example conversations

### Developer (World 1)

```
You: I have ./inventory-api and ./store-api cloned, set everything up for me locally

Claude: I'll walk you through World 1. First, let me check your cluster…
  [reads klight://cluster — no cluster found]
  → calling local_setup(cpus=4, memory=4096)
  ✓ Cluster klight-demo started

  Now preloading infra images to avoid ImagePullBackOff…
  → calling preload_infra()
  ✓ postgres, redis pulled and loaded

  Building your services…
  → calling local_build_load("inventory-api", "./inventory-api")
  → calling local_build_load("store-api", "./store-api")
  ✓ Both images loaded into minikube

  Deploying to env dev…
  → calling deploy_from_repos(["./inventory-api", "./store-api"], "dev")
  ✓ inventory-api  Running (1/1)
  ✓ store-api      Running (1/1)
  All ready in 38s. Visit http://localhost:8081 after: klight open inventory-api --env dev
```

### DevOps (World 3 setup)

```
You: set up our staging cluster for klight and give me the token for the team

Claude: [reads klight://cluster — context is staging-eks]
  → calling setup_remote_cluster()
  ✓ Namespace klight-system created
  ✓ ServiceAccount klight-dev created
  ✓ ClusterRole klight-dev (env-* namespaces)
  Token (valid 1 year): eyJhbGci...

  Share this with your devs:
    klight connect --url https://staging.company.k8s --token eyJhbGci...
  Or ask me to call connect_remote for them.
```

### Team lead (daily ops)

```
You: what's the state of all environments right now?

Claude: [reads klight://environments automatically]
  3 active environments:
  env-alice  store profile  3/3 Running ✓
  env-bob    store profile  2/3 Running  ← store-web Pending
  env-dev    store profile  3/3 Running ✓

  env-bob has a problem. Want me to check what's wrong?

You: yes

Claude: → calling get_unready("bob")
  store-web: Pending — ImagePullBackOff
  ghcr.io/slothlabsorg/store-web:main not found in registry
  Fix: push a new build to ghcr.io, or use replace_service to load a local build
```

---

## Verify installation

```bash
# Check tools load correctly
python3 -c "from klight.mcp_server import mcp; print([t.name for t in mcp._tool_manager.list_tools()])"

# Inspect interactively (browser UI, no Claude needed)
npx @modelcontextprotocol/inspector klight mcp
# Opens http://localhost:5173 — call tools, inspect resources
```
