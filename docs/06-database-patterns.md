# Database Patterns

## How databases work in klight

Each environment gets its own database instance (StatefulSet + PVC). No shared databases between environments.

Available in the default catalog: `postgres`, `mysql`, `mongodb`, `redis`

## Declaring database needs

```yaml
# klight.yaml
needs: [postgres]
env:
  DB_HOST: postgres       # service DNS within namespace
  DB_PORT: "5432"
  DB_NAME: my_service_db
  DB_USER: klight
```

klight spins up a `postgres` StatefulSet in the namespace. Multiple services that declare `needs: [postgres]` share the same StatefulSet but use different databases.

## Migration jobs

```yaml
# klight.yaml
migration:
  command: ["python", "-m", "app.migrate"]   # runs inside your service image
```

klight creates a K8s Job that:
1. Waits for postgres via sentinel
2. Runs the migration command
3. Exits (the service then starts)

The migration is idempotent — safe to run multiple times.

## Running migrations manually

```bash
klight db migrate my-api --env alice
```

Deletes the old job (if exists) and re-runs it.

## Accessing databases

```bash
klight db connect postgres --env alice          # open psql
klight db connect postgres --env alice --db my_api_db  # specific database
klight db query --env alice --db my_api_db "SELECT count(*) FROM users"
```

## Multiple Postgres versions

Add to `klight-catalog.yaml`:
```yaml
postgres14:
  image: postgres:14-alpine
  port: 5432
  manifest: infrastructure/postgres14/base
  provides:
    GLOBAL_POSTGRES14_HOST: postgres14
```

Then: `needs: [postgres14]`

## LocalStack for S3, SQS, DynamoDB

```yaml
needs: [localstack]
env:
  AWS_ENDPOINT_URL: http://localstack:4566   # auto-provided by catalog
  S3_BUCKET_NAME: my-bucket
  AWS_DEFAULT_REGION: us-east-1
```

LocalStack starts automatically. Your service uses the SDK normally — just with `endpoint_url` pointing to LocalStack.

## External databases (real infra for debugging)

```yaml
needs:
  postgres:
    mode: external
    POSTGRES_HOST: my-rds.cluster.us-east-1.rds.amazonaws.com
    POSTGRES_PORT: "5432"
```

No StatefulSet created — just injects the env vars pointing to real infra.
