# klight — Handoff Checklist

Manual items that need to be done by hand on whichever machine picks this up
next. klight is a CLI + Helm chart project — no Apple signing needed — but
there's still a Homebrew tap, a public test cluster, and the TiendaDemo
reference suite that need a human.

Status as of last push:
- Launch date: **TBD later in 2026** (slot held until CLI gaps are closed)
- Site: see slothlabs.org `/next/klight/` permalink (TBD copy)
- Companion repo `klight-suite-test/` (TiendaDemo) is the integration test
  harness — keep them in sync

---

## 1. Distribution — must be done by hand

### Homebrew tap (only when ready to ship a public release)
- [ ] Create / update the formula in the `slothlabsorg/homebrew-tap` repo
      (same tap that hosts wattsorbit + cloudorbit casks)
- [ ] `HOMEBREW_TAP_TOKEN` secret on this repo: fine-grained PAT with
      Contents:Write on the tap repo only — same pattern as wattsorbit's
      `update-tap.yml`
- [ ] `.github/workflows/release.yml` should run a `update-tap` step on tag
      push that bumps the formula version + sha256

### GitHub release artifacts
- [ ] Tag `v0.1.0` (or whatever the next semver is) on main; release
      workflow builds binaries for darwin-arm64, darwin-amd64, linux-amd64,
      linux-arm64 and uploads to the GitHub release page
- [ ] `install.sh` script on slothlabs.org / klight page should match the
      release artifact URL pattern — verify after the first tag

### Helm chart registry (when wired up)
- [ ] `oras` push of the `klight-services` Helm chart to a public OCI
      registry (ghcr.io/slothlabsorg/klight) — needs `GHCR_TOKEN` secret
      with packages:write

---

## 2. CLI features — manual smoke tests

Run through these on a fresh machine after `make install` to confirm the
binary is intact.

- [ ] `klight init` on a fresh machine creates `~/.klight/config.yaml`
      with sensible defaults
- [ ] `klight up` on minikube spins up the demo namespace with
      Postgres → Kafka → Redis in dependency order (verify with
      `kubectl get pods -n <ns>` between steps)
- [ ] `klight up --remote eks` against a real EKS context provisions the
      same namespace pattern (test with the test cluster, not prod)
- [ ] `klight down` cleans up the namespace fully — no orphan PVCs, no
      leaked Secrets
- [ ] `klight switch <env>` flips kubeconfig context AND klight's local
      env pointer; `kubectl config current-context` reflects the change
- [ ] **Pending CLI additions** (per project memory):
  - [ ] `klight ps` — list running services in the active namespace
  - [ ] `klight unready` — show pods not ready with last event reason
  - [ ] `klight open <service>` — port-forward + open in browser
  - [ ] `klight local <service>` — swap the in-cluster service with a
        local proxy back to your laptop
- [ ] `klight --version` reports the right semver (matches the tag)

---

## 3. TiendaDemo / klight-suite-test — manual test plan

The companion repo at `~/dev/klight-suite-test/` is the integration test
harness. Keep its plan updated as klight CLI features land.

- [ ] `cd ~/dev/klight-suite-test && klight up` brings the full TiendaDemo
      stack online (frontend + API + Postgres + Kafka + Redis)
- [ ] World 1 → World 3 Playwright suites pass against the spun-up env
      (World 3 screenshots were just refreshed in the last push — re-run
      to confirm no regressions)
- [ ] `klight down` cleans the TiendaDemo namespace fully

See the project memory entry `klight-project.md` for the run checklist
that's pending CLI completion.

---

## 4. News + updater — N/A for klight

klight is a CLI, not a desktop app — there's no NewsBell, no UpdaterModal,
no Tauri updater plugin. Updates happen via `brew upgrade slothlabs/tap/klight`
or the install.sh re-run.

- [ ] Confirm `klight --check-update` (if implemented) prints a clear
      "newer version available" message instead of trying to auto-install

---

## 5. Pre-flight before tagging v0.1.0

- [ ] `make test` is green (Go unit tests cover the CLI)
- [ ] `make e2e` against minikube passes
- [ ] TiendaDemo Playwright Worlds 1–3 all green
- [ ] `install.sh` works on a fresh macOS (Apple Silicon + Intel) and
      a fresh Ubuntu 22.04 box
- [ ] Homebrew formula renders cleanly in `brew install --debug`
- [ ] README install instructions match the actual release artifact path

When everything above is green, tag the version and let CI ship the binaries
+ Homebrew formula bump.

---

## 6. Other items

- [ ] Document the Postgres + Kafka + Redis dependency-order spec
      somewhere durable (not in code comments) — the next contributor
      shouldn't have to read the controller to learn the order
- [ ] Decide on a versioning policy for the Helm chart vs the CLI binary
      — they likely shouldn't share semver
- [ ] If you turn on the public test cluster (the one the docs reference
      for "try it without minikube"), put a kill-switch + cost cap on it
      first — leaving an EKS cluster open to the internet without that is
      asking for a bill spike
