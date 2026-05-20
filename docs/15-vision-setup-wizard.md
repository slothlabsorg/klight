# klight Vision — Setup Wizard + Team Config + Sync

## Una herramienta, dos roles de uso

```
klight setup / klight wizard   ← el responsable (DevOps, tech lead, founder)
klight sync                    ← todos los devs, automático en primer uso del día
klight up / replace / watch    ← todos los devs, operación diaria
```

No son herramientas separadas. El mismo CLI con comandos para diferentes momentos.

---

## El artefacto central: klight-team.yaml

Vive en el repo de infra (o en el mismo repo si es monorepo). Es el índice de todo.

```yaml
version: "1"
team: mycompany

# Dónde vive el resto (profiles, manifests K8s, catalog de infra)
source:
  type: git
  url: https://github.com/mycompany/company-infra
  branch: main

# Targets de cluster
targets:
  local:  klight-demo
  remote: company-dev-cluster
  remote_url: https://k8s.dev.mycompany.com

# Todos los servicios (índice)
services:
  - name: core-api
    image: ghcr.io/mycompany/core-api:main
    repo: https://github.com/mycompany/core-api

  - name: vertical1-api
    image: ghcr.io/mycompany/vertical1-api:main
    repo: https://github.com/mycompany/vertical1-api

# Profiles (qué servicios agrupa cada uno)
profiles:
  core:      [core-api, core-auth]
  vertical1: [core, vertical1-api]
  vertical2: [core, store-web, payments-api]
```

Este es el único URL que el dev necesita para empezar.

---

## Cómo klight resuelve qué hacer en `klight up`

El `klight-team.yaml` es el **índice**. El `klight.yaml` de cada servicio es la **definición completa**.

Cuando el dev hace `klight up vertical1 --env alice`:

```
1. Lee klight-team.yaml → lista de servicios en vertical1: [core-api, vertical1-api]

2. Para CADA servicio, klight busca su klight.yaml en cadena de fallback:
   a. ¿Está el repo clonado localmente? → lee klight.yaml local
   b. ¿Tiene acceso a la API del repo (GitHub/GitLab token)? → descarga klight.yaml
   c. ¿Tiene el infra repo con manifests/services/<name>/? → usa esos manifests K8s
   d. ¿Solo tiene image + port del klight-team.yaml? → genera Deployment mínimo

3. Consolida todos los `needs:` → lista de infra a levantar (postgres, kafka, etc.)

4. Orden de startup:
   → Infra (StatefulSets)
   → Migrations (Jobs)
   → Servicios en orden de dependencias (sentinel)

5. Local: imagePullPolicy: Never (imagen debe estar en minikube)
   Remote: imagePullPolicy: IfNotPresent (imagen se jala del registry)
```

---

## El wizard: `klight setup` / `klight wizard`

### Paso 1 — Plataforma y acceso

```
¿Qué plataforma usás?
  [•] GitHub   [ ] GitLab   [ ] Bitbucket   [ ] GitLab self-hosted   [ ] Otro

Token: ________________
  (read: para leer repos y CI files)
  (write: para abrir PRs automáticos — recomendado)

Organización: mycompany
```

### Paso 2 — Seleccionar repos de servicios

```
Repos en mycompany/ (encontrados: 47)
Seleccioná los que son servicios desplegables:

  [x] core-api           ✓ klight.yaml  ✓ Dockerfile
  [x] core-auth          ✓ klight.yaml  ✓ Dockerfile
  [x] vertical1-api      ⚠ sin klight.yaml  ✓ Dockerfile
  [x] store-web          ⚠ sin klight.yaml  ✓ Dockerfile
  [x] payments-api       ⚠ sin klight.yaml  ⚠ sin Dockerfile (Gradle plugin)
  [ ] analytics-scripts
  [ ] company-docs

(No deben ser cientos. Si hay más de 30, filtrá por nombre o carpeta)
```

### Paso 3 — Repo de infra (si existe)

```
¿Tenés un repo de infra / K8s?
  [x] Sí → company-infra
  [ ] No → klight puede crear uno, o usar el mismo repo del servicio

klight va a escanear company-infra para entender qué hay:
→ Analizando todos los archivos YAML...
```

**Algoritmo de escaneo del repo de infra:**

klight carga en memoria TODOS los YAMLs del repo (sin importar si usan Kustomize, Helm, o archivos sueltos) y los analiza:

```
Archivos encontrados: 143 YAMLs en company-infra/

Infraestructura detectada:
  ✓ StatefulSet/postgres → en k8s/databases/
  ✓ StatefulSet/kafka    → en k8s/messaging/
  ✓ Deployment/redis     → en k8s/cache/

Servicios detectados:
  ✓ Deployment/core-api       → en services/core-api/
  ✓ Deployment/vertical1-api  → en deploy/vertical1/
  ✓ ConfigMap/core-api-config → env vars detectadas

ConfigMaps / env vars encontradas para core-api:
  DB_HOST=postgres, KAFKA_BOOTSTRAP=kafka:9092, REDIS_HOST=redis, JWT_SECRET=***

Cosas que no están:
  ⚠ vertical2-api: no tiene Deployment en infra repo → se generará minimal
  ⚠ payments-api: no se encontraron env vars → se completará en Paso 4
```

El algoritmo funciona con cualquier estructura:
- Kustomize con overlays: detecta base + overlay
- Archivos sueltos (deployment.yaml + service.yaml + configmap.yaml)
- Mezcla de ambos
- Sin importar profundidad de carpetas

### Paso 4 — Por cada servicio sin klight.yaml

Para cada servicio seleccionado que no tiene klight.yaml, klight propone uno basado en:
- Lo detectado del Dockerfile (puerto, framework)
- Lo detectado de CI files (imagen Docker)
- Lo detectado de los manifests K8s existentes (env vars, infra needs)

```
vertical1-api — análisis:
  Puerto:       8080 (del Dockerfile EXPOSE)
  Framework:    Spring Boot (build.gradle.kts + spring-boot-starter)
  Imagen CI:    ghcr.io/mycompany/vertical1-api:main
                (encontrado en .github/workflows/build.yml línea 34)
  Infra needs:  postgres, kafka (del ConfigMap en company-infra/services/vertical1-api/)
  Env vars:     DB_HOST=postgres, KAFKA_BOOTSTRAP=kafka:9092, CORE_API_URL=http://core-api:8080
                (extraídas del ConfigMap k8s existente)
  Manifests K8s: ✓ en company-infra/deploy/vertical1/base/

klight.yaml propuesto:
─────────────────────────────────────────────────
name: vertical1-api
port: 8080
health: /actuator/health
image: ghcr.io/mycompany/vertical1-api:main
manifest: ../company-infra/deploy/vertical1/base  ← usa los K8s existentes
needs: [postgres, kafka]
env:
  DB_HOST: postgres
  KAFKA_BOOTSTRAP_SERVERS: kafka:9092
  CORE_API_URL: http://core-api:8080
─────────────────────────────────────────────────
¿Confirmás? [Sí / Editar]

payments-api — análisis:
  Puerto:       8082 (del Dockerfile)
  Framework:    Kotlin Spring Boot + Jib (sin Dockerfile estándar)
  Imagen CI:    ⚠ no encontrada — necesitás completarla:
                > ghp.io/mycompany/payments-api:main
  Infra needs:  postgres (detectado del K8s en infra repo)
  Env vars:     DB_HOST=postgres, STRIPE_KEY=*** (secret — dejar vacío)
  Manifests K8s: ✓ en company-infra/services/payments-api/overlays/dev/
─────────────────────────────────────────────────
name: payments-api
port: 8082
health: /actuator/health
image: ghp.io/mycompany/payments-api:main   ← completado por el responsable
build:
  command: ./gradlew payments:jib --image=payments-api:local
  context: .
manifest: ../company-infra/services/payments-api/overlays/dev
needs: [postgres]
env:
  DB_HOST: postgres
  STRIPE_KEY: ""    ← secreto — el dev completa en su .env local
─────────────────────────────────────────────────
```

### Paso 5 — Profiles

```
Agrupá los servicios en profiles:

Profile "core":
  [x] core-api  [x] core-auth

Profile "vertical1":
  [x] Incluir → core (como base)
  [x] vertical1-api

Profile "vertical2":
  [x] Incluir → core
  [x] store-web  [x] payments-api
```

### Paso 6 — Generar y distribuir

```
klight va a:

  PRs a crear automáticamente:
  → mycompany/vertical1-api: agregar klight.yaml
  → mycompany/store-web: agregar klight.yaml
  → mycompany/payments-api: agregar klight.yaml (imagen a confirmar)

  En company-infra:
  → Crear manifests/profiles/core.yaml
  → Crear manifests/profiles/vertical1.yaml
  → Crear manifests/profiles/vertical2.yaml
  → Crear klight-team.yaml

  ¿Abrir PRs automáticamente? [Sí / Descargar archivos para hacerlo manual]

Listo. Compartí este comando con tu equipo:
  klight sync https://raw.githubusercontent.com/mycompany/company-infra/main/klight-team.yaml
```

---

## El dev: flujo completo desde cero

### Primera vez (recibe el link del responsable)

```bash
pip install klight
klight sync https://raw.githubusercontent.com/.../klight-team.yaml
# → descarga y guarda en ~/.klight/teams/mycompany.yaml
# → configura targets: local=klight-demo, remote=company-dev
# → muestra: "Team 'mycompany' configurado. Profiles disponibles: core, vertical1, vertical2"
```

### Inicio del día (automático)

```bash
klight up vertical1 --env alice
# klight verifica si klight-team.yaml cambió desde ayer
# Si cambió: "Actualizando config (1 servicio nuevo: billing-api)"
# Levanta todo con las últimas imágenes de main
```

### El dev trabaja en UN servicio

```bash
# Clona SOLO el repo que le interesa
git clone vertical1-api && cd vertical1-api

# El stack ya corre con imágenes de CI
# Reemplaza solo su servicio con build local
klight replace vertical1-api --with . --env alice
# → docker build -t vertical1-api:local .
# → local: minikube image load
# → remote: necesita registry (ver abajo)
# → kubectl rollout restart deployment/vertical1-api

klight watch vertical1-api --env alice   # hotreload

# Vuelve a CI cuando termina
klight restore vertical1-api --env alice
```

### Imágenes en modo remote: `klight replace`

```
Opciones de resolución (en orden de simpleza):

1. Dev tiene permisos en el registry:
   → klight buildea, hace push a ghcr.io/mycompany/vertical1-api:local-alice
   → actualiza el deployment con esa imagen

2. Dev no tiene permisos:
   → klight informa: "No tenés permisos para push a ghcr.io/mycompany"
   → Opción A: DevOps le da acceso (recomendado)
   → Opción B: usar registry in-cluster

3. Registry in-cluster (opción B, DevOps lo habilita una vez):
   → klight puede deployar un registry simple (registry:2) en el cluster
   → El dev pushea ahí: localhost:5000/vertical1-api:local
   → Solo accesible desde dentro del cluster
   → Cada dev tiene su namespace → no hay colisiones

4. Casos donde nadie se molesta porque es remoto:
   → Muchos devs prefieren trabajar en local para iterar
   → Solo van a remote cuando quieren integración real con otros servicios
```

---

## Los cuatro mundos

### Mundo 1 — Solo / micro-equipo (1-3 devs, monorepo o pocos repos)

```
Setup:
  klight init ./service-a    # genera klight.yaml
  klight init ./service-b
  → klight-team.yaml no es necesario
  → No hay infra repo separado

Daily:
  klight from-repos ./* --env alice
  # O con kustomize existente:
  klight from-repos ./service-a --env alice   # lee klight.yaml con manifest: ./deploy/

Wizard aplica: parcialmente. Solo los pasos de init individual, sin el team setup.
```

### Mundo 2 — Early startup (3-10 devs, repos separados, sin DevOps)

```
Setup (tech lead, una vez):
  klight setup
  → selecciona repos
  → crea klight-team.yaml en un repo
  → abre PRs con klight.yaml en cada servicio

Daily (dev):
  klight sync                              # jala latest desde klight-team.yaml
  klight up vertical1 --env alice          # CI images
  klight replace mi-servicio --with .      # trabaja solo en su servicio

Sin infra repo formal: klight-team.yaml en repo compartido, manifests generados.
```

### Mundo 3 — Startup con DevOps (10-30 devs, infra repo, cluster remoto planificado)

```
Setup (DevOps):
  klight setup
  → escanea infra repo existente (detecta K8s, configmaps, etc.)
  → genera klight-team.yaml + profiles
  → PRs a service repos para agregar klight.yaml
  → configura targets: local + remote cuando el cluster esté listo

Daily (dev):
  klight use local            # o klight use remote
  klight up vertical1 --env alice
  klight replace mi-servicio --with .
```

### Mundo 4 — Empresa mediana (30-100 devs, clusters por vertical/ambiente)

```
Setup (DevOps, con CI pipeline):
  klight setup + CI que valida klight.yaml en cada PR de servicio
  → staging/dev profiles que usan tags de branches: ghcr.io/co/svc:develop
  → production profiles: ghcr.io/co/svc:main

Daily (dev):
  klight use remote
  klight up vertical1 --env alice        # env-alice en cluster
  klight replace mi-servicio --with .    # push a registry de dev
```

---

## Mantenimiento: quién hace qué

| Evento | Responsable | Acción |
|---|---|---|
| Se crea un nuevo servicio | Service team | Agrega klight.yaml al repo (o corre klight init) |
| Servicio cambia puerto / health | Service team | Actualiza klight.yaml (mismo commit) |
| Servicio agrega nueva dep (Redis) | Service team | Actualiza needs: y env: en klight.yaml |
| Se agrega servicio a un vertical | DevOps team | Actualiza profiles/vertical1.yaml en infra repo |
| Hay un nuevo infra disponible (ElasticSearch) | DevOps team | Agrega a klight-catalog.yaml + StatefulSet manifest |
| Dev hace `klight up` | klight | Auto-sync si klight-team.yaml cambió desde ayer |

**CI recomendado (opcional, propuesto por DevOps):**
- En PR de servicio: `klight validate klight.yaml` — valida JSON Schema + catalog
- En PR de infra repo: `klight check-team klight-team.yaml` — todos los servicios tienen klight.yaml

---

## Lo que queda para la UI

La UI (`klight ui`) debe cubrir el wizard visualmente:
- Tab "Setup" para el responsable
- Enrollment de repos via plataforma (GitHub/GitLab/Bitbucket)
- Escaneo visual de K8s existentes con toggle para confirmar/editar
- Generación de klight.yaml por servicio con campos editables
- Estado del team: qué servicios tienen klight.yaml, cuáles no
- "Distribute" button: abre PRs o descarga archivos

---

## Componentes a construir (orden sugerido)

1. **`klight sync <url>`** — descarga y aplica klight-team.yaml
2. **`klight replace <service> --with <path>`** — swap local build
3. **`klight restore <service>`** — vuelve a imagen de CI
4. **K8s scanner** — lee todos los YAMLs de un repo/folder, extrae servicios, infra, env vars
5. **`klight setup`** — wizard CLI interactivo (plataforma → repos → scan → generate → PR)
6. **UI: Setup tab** — el wizard anterior pero en browser
7. **Auto-sync en startup** — klight verifica cambios en klight-team.yaml al correr `klight up`
8. **Registry in-cluster** — para el caso remote sin permisos de push

---

## Orden de implementación + validación GitHub

### Fase 1 — Core dev workflow
1. `klight replace <service> --with <path> --env <name>` — swap servicio con build local
2. `klight restore <service> --env <name>` — vuelve a imagen de CI del klight-team.yaml
3. `klight sync <url>` — descarga y aplica klight-team.yaml a config local del dev

### Fase 2 — Setup wizard
4. K8s scanner — carga todos los YAMLs de un repo/folder en memoria, extrae infra, env vars, services
5. `klight setup` / `klight wizard` — CLI interactivo: plataforma → repos → scan → generate → PR
6. Auto-sync en startup — `klight up` verifica si klight-team.yaml cambió desde ayer

### Fase 3 — UI wizard
7. Tab "Setup" en `klight ui` — el wizard visual: enrollment de repos, scan K8s, confirmar klight.yaml

### Fase 4 — Workshop + validación real con GitHub (slothlabsorg)
8. Crear repos en slothlabsorg:
   - `klight-demo-infra` — infra repo con manifests K8s + profiles + klight-team.yaml
   - `klight-demo-store-api` — Python FastAPI + klight.yaml
   - `klight-demo-inventory-api` — Python FastAPI + Kafka + klight.yaml
   - `klight-demo-store-web` — React Vite + nginx + klight.yaml
   - `klight-demo-sales-recorder` — Node.js con deploy/ folder + klight.yaml

9. Ejecutar escenario completo:
   - `klight sync` desde URL del infra repo
   - `klight local setup` + `klight preflight --fix`
   - `klight env create tienda`
   - `klight up store --env tienda` (usa imágenes de registry)
   - `klight replace store-api --with ./klight-demo-store-api --env tienda` (dev trabaja en 1)
   - Verificar checklist de 18 puntos
   - `klight env destroy tienda --yes`

10. Documentar como Workshop completo (página web futura):
    - Mundo 1: dev solo con `klight from-repos`
    - Mundo 2: equipo con klight.yaml por repo + `klight sync`
    - Mundo 3: DevOps team con infra repo + profiles + `klight up`
    - Cada mundo con capturas, comandos exactos, tiempos estimados

