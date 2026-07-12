# Diagramas klight — escenarios y plataforma

Complemento visual de [00-manual-por-rol.md](../00-manual-por-rol.md) y [ARCHITECTURE.md](../../ARCHITECTURE.md).

---

## World 1 vs 2 vs 3 — flujo de imágenes

```mermaid
flowchart TB
  subgraph W1 [World 1 — código local]
    D1[Dev laptop]
    DK[docker build]
    MK[minikube image load]
    FR[from-repos]
    D1 --> DK --> MK --> FR
  end

  subgraph W2 [World 2 — CI images local]
    SYNC[klight sync]
    REG[Container registry]
    UP2[klight up]
    SYNC --> UP2
    REG -.->|imagePullPolicy IfNotPresent| UP2
  end

  subgraph W3 [World 3 — cluster remoto]
    DO[DevOps setup-remote]
    CON[klight connect]
    UP3[klight up]
    EKS[EKS / GKE / AKS]
    DO --> EKS
    CON --> UP3 --> EKS
  end
```

---

## Artefactos y responsabilidades

```mermaid
erDiagram
  KLIGHT_YAML ||--o{ SERVICE : defines
  PROFILE ||--o{ SERVICE : groups
  KLIGHT_TEAM ||--o{ PROFILE : indexes
  KLIGHT_TEAM ||--o{ SERVICE : image_registry
  CATALOG ||--o{ KLIGHT_YAML : resolves_needs
  KLIGHT_TOML ||--|| TARGET : cluster_target

  KLIGHT_YAML {
    string name
    int port
    list needs
    list depends
    map env
  }
  PROFILE {
    string name
    list infrastructure
    list services
  }
  KLIGHT_TEAM {
    string version
    string team
    object source
    list services
  }
```

---

## Sentinel y orden de arranque

```mermaid
flowchart TD
  infra[Infra StatefulSets<br/>postgres kafka redis]
  mig[Migration Jobs]
  s1[inventory-api<br/>sentinel waits postgres+kafka]
  s2[store-api<br/>sentinel waits postgres+kafka+inventory-api]
  s3[store-web<br/>sentinel waits store-api]

  infra --> mig
  mig --> s1
  s1 --> s2
  s2 --> s3
```

---

## TiendaDemo — topología (referencia)

Ver diagramas detallados en [klight-suite-test/docs/ARCHITECTURE.md](https://github.com/slothlabsorg/klight-suite-test/blob/main/docs/ARCHITECTURE.md):

1. Servicios dentro del namespace
2. Secuencia de una venta
3. Workflow del desarrollador con klight
4. Local vs EKS
5. Scope cluster vs namespace

---

## Perfiles TiendaDemo

| Profile | Servicios | Uso |
|---------|-----------|-----|
| `store` | inventory-api, store-api, store-web | Checklist 18 puntos |
| `store-extended` | + billing-service, sales-recorder, localstack | Demo Kotlin + manifest: |
