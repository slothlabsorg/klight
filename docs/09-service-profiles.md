# Service Profiles

## What is a profile?

A YAML file that declares a named group of services to start together. Used in DevOps-managed infra repos. Profiles support `includes:` to compose from shared profiles.

## Basic profile

```yaml
# manifests/profiles/backend.yaml
name: backend
description: "Core backend stack"

infrastructure: [postgres, redis, kafka]

migrations:
  - job: my-api-dbmigrate
    db: my_api_db

services:
  - name: my-api
  - name: my-worker

healthChecks:
  - my-api:8080/health
  - my-worker:8081/health
```

```bash
klight up backend --env alice
```

## Profile composition with includes:

```yaml
# manifests/profiles/core.yaml
name: core
infrastructure: [postgres, kafka]
services:
  - name: core-auth
  - name: core-api

# manifests/profiles/vertical2.yaml
name: vertical2
includes: [core]           # starts core-auth + core-api first
services:
  - name: vertical2-api    # starts after core is healthy
```

```bash
klight up vertical2 --env alice
# Starts: postgres, kafka, core-auth, core-api, vertical2-api
# In the right order, with health checks at each stage
```

## Service entry formats

```yaml
services:
  - name: my-api           # simple: uses manifests/services/my-api/
  
  - name: my-api           # with extra options:
    image: ghcr.io/org/my-api:main   # override CI image
```

## Profile with klight.yaml repos

Profiles can reference repos with `klight.yaml` instead of infra-repo manifests. Future feature: `klight up --profile ./profiles/backend.yaml --repos ./my-api ./my-worker --env alice`

Currently: use `klight from-repos` for repo-based deployments, `klight up` for profile-based ones.

## Listing profiles

```bash
klight profile list    # shows all profiles in manifests/profiles/
```
