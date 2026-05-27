# Datadog Alert Lamp — Functional Plan and Architecture

> **Status**: Proposal · **Last updated**: May 26, 2026

---

## 1. Context and motivation

Datadog alerts currently arrive over Slack and email. Two practical limits:

- **Cognitive saturation**: Slack is already noisy. A P1 drowns in the flood of team notifications, CI updates, bots, and SOS channels.
- **Off-screen**: when you're not in front of your machine (coffee, meeting next door, standing at the whiteboard), a silent notification goes unnoticed.

A **dedicated physical lamp**, sitting next to your screens, that pulses red the moment a critical monitor fires, restores an out-of-band alert channel — peripheral but impossible to miss. It's the modern version of the NOC-room beacon, individual and at $50.

The goal is **not** to replace Slack/PagerDuty, but to add a **peripheral physical signal** that complements them for the most important alerts.

---

## 2. Functional requirements

### 2.1 User stories

| # | As a…                  | I want…                                                                        | So that…                                                               |
|---|------------------------|--------------------------------------------------------------------------------|------------------------------------------------------------------------|
| 1 | Platform engineer      | my lamp pulses red as soon as a P1 monitor triggers                            | I'm alerted even when I'm not looking at my screen                     |
| 2 | Platform engineer      | the lamp goes back to calm (green or off) on recovery                          | I can see at a glance that the incident is resolved                    |
| 3 | Platform engineer      | I can distinguish warning, error, and recovery                                 | I can prioritize without having to read the notification               |
| 4 | Engineering Director   | to deploy the system with no server to maintain                                | this stays a side project, not technical debt                          |
| 5 | Engineering Director   | the whole chain to cost less than $5/month                                     | we stay on the free tier of every provider                             |
| 6 | Platform engineer      | to route only monitors tagged `alert_lamp:true`                                | I'm not flooded by every Datadog alert in the account                  |

### 2.2 Use cases

1. **An `error` monitor triggers** → the lamp pulses red for ~7 s (12 cycles at 0.6 s), then returns to its previous state.
2. **A `warning` monitor triggers** → the lamp pulses orange for ~6 s (6 cycles at 1 s).
3. **Recovery** → the lamp breathes green for ~4.5 s (3 cycles at 1.5 s).
4. **No Data** → the lamp breathes purple to signal "signal lost" (to distinguish it from a real trigger).

### 2.3 Non-functional

- **Target latency**: < 5 s between Datadog trigger and the start of the flashing.
- **Target availability**: best-effort. A lost alert is not an incident — Slack/PagerDuty remain the source of truth.
- **Target cost**: $0 recurring (free tiers), $50 one-time hardware.

---

## 3. Scope

### 3.1 In-scope

- One LIFX bulb per workstation.
- Notifications from Datadog only (EU account).
- Visual effects limited to the `pulse` and `breathe` modes of the LIFX API.
- Individual deployment (each engineer who wants a lamp deploys it for themselves).

### 3.2 Out-of-scope (v1)

- Multi-user mode (one lamp per team with acknowledgment, etc.).
- PagerDuty / Opsgenie integration (Datadog is enough for the initial need).
- Acknowledging the alert via a physical button.
- Audio (siren, voice): too intrusive in an openspace office.
- Synchronization between several lamps.

---

## 4. Architectural principles

| # | Principle                           | Concrete consequence                                                                                                 |
|---|-------------------------------------|----------------------------------------------------------------------------------------------------------------------|
| 1 | **Serverless or nothing**           | No VM, no Pi, no Docker. Cloudflare Worker only.                                                                     |
| 2 | **Strict free tier**                | 100k req/day on CF Workers + 60 req/min on LIFX = far more than enough. No paid service.                             |
| 3 | **Stateless by default**            | The Worker stores nothing between requests. Any state (deduplication) is offloaded to CF KV, optional.               |
| 4 | **Single responsibility**           | The Worker translates `Datadog alert → LIFX call`. No business logic, no complex routing.                            |
| 5 | **Best-effort, acknowledged**       | If the lamp misses an alert, Slack and PagerDuty remain the source of truth. No aggressive retry, no ACK.            |
| 6 | **Minimal but real security**       | Shared token in an HTTP header. No mTLS, no OAuth, but never any secret in cleartext in the code.                    |
| 7 | **Reversibility**                   | If LIFX shuts down its API or raises prices: swap the bulb for a Shelly and change ~10 lines in the Worker.          |
| 8 | **No home-automation orchestration**| No Home Assistant, no Node-RED. Datadog → Cloudflare → LIFX Cloud → bulb. Three hops, that's it.                     |

---

## 5. Target architecture

### 5.1 Flow diagram

```
┌────────────────────┐
│  Datadog Monitor   │
│      (EU site)     │
└──────────┬─────────┘
           │ Webhook POST
           │ + X-Webhook-Token header
           ▼
┌────────────────────────────────────┐
│  Cloudflare Worker (Python)        │
│  - Auth (shared secret)            │
│  - Map alert_type → LIFX effect    │
│  - (optional) 30s KV dedup         │
└──────────┬─────────────────────────┘
           │ HTTPS POST /v1/lights/.../effects/pulse
           │ + LIFX Bearer token
           ▼
┌────────────────────┐
│   LIFX Cloud API   │
└──────────┬─────────┘
           │ TCP push to the bulb
           ▼
┌────────────────────┐
│   LIFX A60 bulb    │
│   (home Wi-Fi)     │
└────────────────────┘
```

### 5.2 Components

| Component            | Role                                                  | Hosting           | Cost          |
|----------------------|-------------------------------------------------------|-------------------|---------------|
| Datadog Monitor      | Source of the event                                   | SaaS (existing)   | already paid  |
| Datadog Webhook      | HTTP push to the Worker                               | SaaS              | included      |
| Cloudflare Worker    | Translation & routing `alert → LIFX effect`           | Cloudflare edge   | $0            |
| Cloudflare KV (opt.) | Deduplication by `monitor_id` over a 30 s window      | Cloudflare        | $0 (<100k)    |
| LIFX Cloud           | Relay to the bulb                                     | LIFX SaaS         | $0            |
| LIFX A60 bulb        | Physical output                                       | Home              | $50 one-time  |

### 5.3 Nominal flow

1. A monitor `service:api env:prod` tagged `alert_lamp:true` transitions to `Alert`.
2. Datadog evaluates the `@webhook-lifx-alert` notification present in the message.
3. Datadog POSTs to `https://datadog-lifx-alert.<sub>.workers.dev` with a templated payload and the `X-Webhook-Token` header.
4. The Worker authenticates, reads `alert_type` and `transition`, and picks the profile.
5. The Worker POSTs to `https://api.lifx.com/v1/lights/label:Alert/effects/pulse` with the Bearer token.
6. LIFX Cloud relays the command to the bulb, which flashes for ~7 s then returns to its initial state.
7. On recovery, same chain, "success" profile (green, breathe).

### 5.4 Worker configuration

```toml
# wrangler.toml
name = "datadog-lifx-alert"
main = "src/worker.py"
compatibility_date = "2026-01-01"
compatibility_flags = ["python_workers"]

[vars]
LIFX_SELECTOR = "label:Alert"
```

Secrets (never in cleartext in the repo):

- `LIFX_TOKEN`: LIFX Bearer, created at https://cloud.lifx.com/settings.
- `SHARED_SECRET`: random ≥ 32 characters, shared with the Datadog webhook header.

### 5.5 Datadog configuration

Webhook integration:
- **URL**: `https://datadog-lifx-alert.<sub>.workers.dev`
- **Custom headers**: `{"X-Webhook-Token": "<SHARED_SECRET>"}`
- **Payload**:
  ```json
  {
    "alert_type": "$ALERT_TYPE",
    "transition": "$ALERT_TRANSITION",
    "monitor_id": "$ALERT_ID",
    "title": "$EVENT_TITLE"
  }
  ```

On the monitor side: add `@webhook-lifx-alert` to the message, scoped via a tag policy or explicitly per monitor.

---

## 6. Security

| Risk                                                         | Mitigation                                                                                  |
|--------------------------------------------------------------|---------------------------------------------------------------------------------------------|
| Someone discovers the Worker URL and triggers random flashes | `X-Webhook-Token` header (401 if missing or wrong)                                          |
| LIFX token exfiltrated                                       | Stored as a CF secret, never in cleartext. Revocable from the LIFX dashboard in one click.  |
| Internal data exposure in the payload                        | The payload contains only `alert_type`, `transition`, `monitor_id`, `title`. No PII.        |
| MITM between Datadog and the Worker                          | End-to-end TLS (Cloudflare manages the certificate).                                        |
| Cloudflare compromise                                        | Residual risk accepted. The blast radius is "lamp flashing into the void."                  |
| LIFX Cloud compromise                                        | Residual risk accepted. Same.                                                               |

**Non-goal**: this system is not a secure alerting channel. No sensitive data should flow through this chain. The monitor `title` is deliberately left in cleartext for debugging, but the Worker could truncate or hash it if needed.

---

## 7. Observability

Meta-question: how do we know the lamp itself is broken?

| Symptom                             | Detection                                                                         |
|-------------------------------------|-----------------------------------------------------------------------------------|
| Worker down                         | Cloudflare dashboard (free logs and request/error metrics).                       |
| Bulb offline (Wi-Fi down)           | LIFX response `offline` in `results[].status`. Log it on the Worker side.         |
| LIFX API down                       | HTTP 5xx surfaced in the Worker logs.                                             |
| Datadog stops sending               | Detected manually (monthly test) or via a canary monitor that self-triggers daily.|

**v1 recommendation**: no monitoring of the monitoring. Weekly manual test by triggering the webhook via `curl`. If needed in v2, add a Datadog canary monitor that self-fires daily at a fixed time and someone visually checks the lamp flashed (human eyeballs, not instrumented).

---

## 8. Roadmap

### v1 — MVP (one evening)
- Python Worker deployed, secrets configured.
- A single test monitor, `error` profile only.
- Visual validation.

### v2 — Full profiles (2 h)
- Full mapping `error / warning / success / info`.
- Recovery logic.
- Structured logs.

### v3 — Hardening (optional, 2 h)
- CF KV deduplication (30 s window per `monitor_id`).
- Daily canary test.
- README documentation for colleagues who want their own lamp.

### v4 — Future ideas (uncommitted)
- Physical button (Shelly Plus 1 or a Zigbee button) to acknowledge the alert → turn off the lamp.
- "Deploy in progress" profile triggered from GitHub Actions (slow blue).
- "Focus" mode: when manually enabled, ignore warnings.

---

## 9. Risks and limits

| Risk                                                         | Likelihood  | Impact | Mitigation                                          |
|--------------------------------------------------------------|-------------|--------|------------------------------------------------------|
| LIFX shuts down or restricts its cloud API                   | Low         | Medium | Reversibility to Shelly (~10 lines to change)        |
| Home Wi-Fi down                                              | Medium      | Low    | Best-effort accepted, Slack fallback always present  |
| Datadog changes its webhook format                           | Very low    | Low    | Payload is templated on the Datadog side, not forced |
| Cloudflare Python Workers break (still in open beta)         | Low         | Low    | Equivalent JS Worker fallback (~25 lines)            |
| LIFX rate-limit saturation (60 req/min)                      | Very low    | Low    | KV dedup if needed                                   |
| Reflex of wiring the lamp to too many monitors               | High        | Medium | Discipline: only monitors tagged `alert_lamp:true`   |

---

## 10. Key technical decisions

| # | Decision                                          | Alternative rejected           | Short rationale                                                        |
|---|---------------------------------------------------|--------------------------------|------------------------------------------------------------------------|
| 1 | LIFX Color A60 bulb                               | Hue                            | No $50 bridge needed, direct REST API, no OAuth                        |
| 1 | LIFX Color A60 bulb                               | Tapo L530E                     | Recurring CVEs + Chinese cloud + no public API                         |
| 1 | LIFX Color A60 bulb                               | WiZ                            | No public cloud API, local UDP incompatible with the Worker            |
| 1 | LIFX Color A60 bulb                               | Shelly Duo RGBW                | LIFX is more mature on native `pulse`/`breathe` effects. Shelly stays the EU plan B.|
| 1 | LIFX Color A60 bulb                               | Govee                          | Chinese cloud (same category of doubt as Tapo)                         |
| 2 | Cloudflare Worker (Python)                        | AWS Lambda                     | More generous free tier, simpler deployment, global edge               |
| 2 | Cloudflare Worker (Python)                        | JS Worker                      | Personal preference for Python. JS fallback if the beta is unstable.   |
| 3 | Native Datadog webhook                            | Polling the Datadog API        | Push > pull, better latency and cost                                   |
| 4 | `X-Webhook-Token` header                          | mTLS, HMAC signature           | Acceptable simplicity given the stakes (a flashing lamp)               |

---

## 11. Appendices

### A. Useful LIFX selectors

| Selector             | Effect                                           |
|----------------------|--------------------------------------------------|
| `all`                | Every bulb on the account                        |
| `label:Alert`        | Bulb(s) named `Alert` in the LIFX app            |
| `group:Bureau`       | Every bulb in the `Bureau` group                 |
| `id:d073d5...`       | A specific bulb by MAC                           |

### B. Datadog variables available in the webhook

| Variable               | Example                                  |
|------------------------|------------------------------------------|
| `$ALERT_TYPE`          | `error`, `warning`, `success`, `info`    |
| `$ALERT_TRANSITION`    | `Triggered`, `Recovered`, `Re-Triggered` |
| `$ALERT_ID`            | `1234567`                                |
| `$EVENT_TITLE`         | `[Triggered] API p95 > 500ms`            |
| `$EVENT_MSG`           | The full monitor body                    |

### C. Reference links

- LIFX HTTP API: https://api.developer.lifx.com/
- Cloudflare Workers (Python): https://developers.cloudflare.com/workers/languages/python/
- Datadog Webhooks: https://docs.datadoghq.com/integrations/webhooks/
