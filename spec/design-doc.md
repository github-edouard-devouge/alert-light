# Lampe d'alerte Datadog — Plan fonctionnel et architecture

> **Statut** : Proposition · **Dernière maj** : 26 mai 2026

---

## 1. Contexte et motivation

Les alertes Datadog arrivent aujourd'hui par Slack et e-mail. Deux limites pratiques :

- **Saturation cognitive** : Slack est déjà bruyant. Une P1 se noie dans le flux des notifs d'équipe, des CI, des bots, des canaux SOS.
- **Hors-écran** : quand on n'est pas devant la machine (café, réunion à côté, debout devant le whiteboard), une notif silencieuse passe inaperçue.

Une **lampe physique dédiée**, posée à côté des écrans, qui pulse en rouge dès qu'un monitor critique se déclenche, restaure un canal d'alerte hors-bande, périphérique mais impossible à manquer. C'est la version moderne du gyrophare de salle de NOC, en version individuelle et à 50 €.

L'objectif n'est **pas** de remplacer Slack/PagerDuty, mais d'ajouter un **signal physique périphérique** complémentaire pour les alertes les plus importantes.

---

## 2. Besoin fonctionnel

### 2.1 User stories

| # | En tant que…           | Je veux…                                                                       | Pour…                                                                  |
|---|------------------------|--------------------------------------------------------------------------------|------------------------------------------------------------------------|
| 1 | Ingénieur platform     | que ma lampe pulse en rouge dès qu'un monitor P1 trigger                       | être alerté même sans regarder mon écran                               |
| 2 | Ingénieur platform     | que la lampe redevienne calme (verte ou éteinte) au recovery                   | savoir visuellement que l'incident est résolu                          |
| 3 | Ingénieur platform     | distinguer warning, error et recovery                                          | prioriser sans avoir à lire la notif                                   |
| 4 | Engineering Director   | déployer le système sans serveur à maintenir                                   | que ça reste un side-project, pas une dette                            |
| 5 | Engineering Director   | que la chaîne complète coûte moins de 5 €/mois                                 | rester sur le free tier des providers                                  |
| 6 | Ingénieur platform     | router seulement les monitors taggés `alert_lamp:true`                         | ne pas être envahi par toutes les alertes Datadog du compte            |

### 2.2 Cas d'usage

1. **Trigger d'un monitor `error`** → la lampe pulse en rouge ~7 s (12 cycles à 0.6 s), puis revient à son état précédent.
2. **Trigger d'un monitor `warning`** → la lampe pulse en orange ~6 s (6 cycles à 1 s).
3. **Recovery** → la lampe respire en vert ~4,5 s (3 cycles à 1,5 s).
4. **No Data** → la lampe respire en violet pour signaler "perte de signal" (à distinguer d'un trigger réel).

### 2.3 Non-fonctionnel

- **Latence cible** : < 5 s entre trigger Datadog et début du clignotement.
- **Disponibilité cible** : best-effort. Une alerte perdue n'est pas un incident — la source de vérité reste Slack/PagerDuty.
- **Coût cible** : 0 € de récurrent (free tiers), 50 € one-shot hardware.

---

## 3. Périmètre

### 3.1 In-scope

- Une seule ampoule LIFX par poste.
- Notification depuis Datadog uniquement (compte EU).
- Effet visuel limité aux modes `pulse` et `breathe` de l'API LIFX.
- Déploiement individuel (chaque ingénieur qui veut une lampe la déploie pour soi).

### 3.2 Out-of-scope (v1)

- Mode multi-utilisateurs (une lampe par équipe avec accusé de réception, etc.).
- Intégration PagerDuty / Opsgenie (Datadog suffit pour le besoin initial).
- Acquittement de l'alerte depuis un bouton physique.
- Audio (sirène, voix) : trop intrusif en open-space.
- Synchronisation entre plusieurs lampes.

---

## 4. Principes d'architecture

| # | Principe                            | Conséquence concrète                                                                                                |
|---|-------------------------------------|---------------------------------------------------------------------------------------------------------------------|
| 1 | **Serverless ou rien**              | Pas de VM, pas de Pi, pas de Docker. Cloudflare Worker uniquement.                                                  |
| 2 | **Free tier strict**                | 100 k req/jour CF Workers + 60 req/min LIFX = très largement suffisant. Aucun service payant.                       |
| 3 | **Stateless par défaut**            | Le Worker ne stocke rien entre deux requêtes. État éventuel (dédoublonnage) délégué à CF KV, optionnel.             |
| 4 | **Une seule responsabilité**        | Le Worker traduit `alert Datadog → appel LIFX`. Pas de logique métier, pas de routage complexe.                     |
| 5 | **Best-effort assumé**              | Si la lampe rate une alerte, Slack et PagerDuty restent les sources de vérité. Pas de retry agressif, pas d'ACK.    |
| 6 | **Sécurité minimale mais réelle**   | Token partagé en header HTTP. Pas de mTLS, pas d'OAuth, mais jamais de secrets en clair dans le code.               |
| 7 | **Réversibilité**                   | Si LIFX ferme son API ou augmente ses prix : on remplace l'ampoule par une Shelly et on change ~10 lignes du Worker.|
| 8 | **Pas d'orchestration domestique**  | Pas de Home Assistant, pas de Node-RED. Datadog → Cloudflare → LIFX Cloud → ampoule. Trois sauts, point.            |

---

## 5. Architecture cible

### 5.1 Diagramme de flux

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
│  - Map alert_type → effet LIFX     │
│  - (option) dédoublonnage 30s KV   │
└──────────┬─────────────────────────┘
           │ HTTPS POST /v1/lights/.../effects/pulse
           │ + Bearer token LIFX
           ▼
┌────────────────────┐
│   LIFX Cloud API   │
└──────────┬─────────┘
           │ TCP push vers ampoule
           ▼
┌────────────────────┐
│  Ampoule LIFX A60  │
│   (Wi-Fi domestique)│
└────────────────────┘
```

### 5.2 Composants

| Composant            | Rôle                                                  | Hébergement       | Coût        |
|----------------------|-------------------------------------------------------|-------------------|-------------|
| Datadog Monitor      | Source de l'événement                                 | SaaS (existant)   | déjà payé   |
| Datadog Webhook      | Émission HTTP vers le Worker                          | SaaS              | inclus      |
| Cloudflare Worker    | Traduction & routage `alert → effet LIFX`             | Cloudflare edge   | 0 €         |
| Cloudflare KV (opt.) | Dédoublonnage par `monitor_id` sur fenêtre 30 s       | Cloudflare        | 0 € (<100k)  |
| LIFX Cloud           | Relais vers l'ampoule                                 | SaaS LIFX         | 0 €         |
| Ampoule LIFX A60     | Rendu physique                                        | Domicile          | 50 € one-shot|

### 5.3 Flux nominal

1. Un monitor `service:api env:prod` taggé `alert_lamp:true` passe en `Alert`.
2. Datadog évalue la notif `@webhook-lifx-alert` présente dans le message.
3. Datadog POST sur `https://datadog-lifx-alert.<sub>.workers.dev` avec un payload templaté et le header `X-Webhook-Token`.
4. Le Worker authentifie, lit `alert_type` et `transition`, choisit le profil.
5. Le Worker POST sur `https://api.lifx.com/v1/lights/label:Alert/effects/pulse` avec le Bearer token.
6. LIFX Cloud relaie l'ordre à l'ampoule, qui clignote ~7 s puis revient à son état initial.
7. Au recovery, même chaîne, profil "success" (vert, breathe).

### 5.4 Configuration du Worker

```toml
# wrangler.toml
name = "datadog-lifx-alert"
main = "src/worker.py"
compatibility_date = "2026-01-01"
compatibility_flags = ["python_workers"]

[vars]
LIFX_SELECTOR = "label:Alert"
```

Secrets (jamais en clair dans le repo) :

- `LIFX_TOKEN` : Bearer LIFX, créé sur https://cloud.lifx.com/settings.
- `SHARED_SECRET` : random ≥ 32 caractères, partagé avec le header webhook Datadog.

### 5.5 Configuration Datadog

Webhook integration :
- **URL** : `https://datadog-lifx-alert.<sub>.workers.dev`
- **Custom headers** : `{"X-Webhook-Token": "<SHARED_SECRET>"}`
- **Payload** :
  ```json
  {
    "alert_type": "$ALERT_TYPE",
    "transition": "$ALERT_TRANSITION",
    "monitor_id": "$ALERT_ID",
    "title": "$EVENT_TITLE"
  }
  ```

Côté monitor : ajouter `@webhook-lifx-alert` dans le message, scoped via une tag policy ou explicitement par monitor.

---

## 6. Sécurité

| Risque                                                    | Mitigation                                                                                  |
|-----------------------------------------------------------|---------------------------------------------------------------------------------------------|
| Quelqu'un découvre l'URL du Worker et déclenche des flashs| Header `X-Webhook-Token` (rejet 401 si absent ou faux)                                       |
| Token LIFX exfiltré                                       | Stocké en CF secret, jamais en clair. Révocable depuis le dashboard LIFX en 1 clic.         |
| Exposition de données internes dans le payload            | Le payload ne contient que `alert_type`, `transition`, `monitor_id`, `title`. Pas de PII.   |
| MITM entre Datadog et Worker                              | TLS de bout en bout (Cloudflare gère le certificat).                                        |
| Compromission de Cloudflare                               | Risque résiduel accepté. L'impact est limité à "lampe qui clignote dans le vide".           |
| Compromission de LIFX Cloud                               | Risque résiduel accepté. Idem.                                                              |

**Non-objectif** : ce système n'est pas un canal d'alerte sécurisé. Aucune donnée sensible ne doit transiter par cette chaîne. Le `title` du monitor est volontairement laissé en clair pour debug, mais le Worker pourrait le tronquer ou le hasher si besoin.

---

## 7. Observabilité

Méta-question : comment savoir que la lampe est en panne ?

| Symptôme                            | Détection                                                                         |
|-------------------------------------|-----------------------------------------------------------------------------------|
| Worker down                         | Cloudflare dashboard (logs, métriques requêtes/erreurs gratuits).                 |
| Ampoule offline (Wi-Fi coupé)       | Réponse LIFX `offline` dans `results[].status`. Logguer côté Worker.              |
| LIFX API down                       | HTTP 5xx remonté dans les logs Worker.                                            |
| Datadog n'envoie plus               | À détecter manuellement (test mensuel) ou via un canary monitor qui s'auto-trigger une fois par jour. |

**Recommandation v1** : pas de monitoring du monitoring. Test manuel hebdo en déclenchant le webhook via `curl`. Si besoin v2, ajouter un canary monitor Datadog qui s'auto-déclenche tous les jours à heure fixe et vérifie que la lampe a flashé (vision humaine, pas instrumenté).

---

## 8. Roadmap

### v1 — MVP (1 soirée)
- Worker Python déployé, secrets configurés.
- Un seul monitor de test, profil `error` uniquement.
- Validation visuelle.

### v2 — Profils complets (2 h)
- Mapping complet `error / warning / success / info`.
- Logique recovery.
- Logs structurés.

### v3 — Hardening (optionnel, 2 h)
- Dédoublonnage CF KV (fenêtre 30 s par `monitor_id`).
- Test canary quotidien.
- Documentation README pour les collègues qui veulent leur lampe.

### v4 — Idées futures (non-engagé)
- Bouton physique (Shelly Plus 1 ou bouton Zigbee) pour acquitter l'alerte → éteindre la lampe.
- Profil "deploy en cours" déclenché par GitHub Actions (bleu lent).
- Mode "focus" : si activé manuellement, ignore les warnings.

---

## 9. Risques et limites

| Risque                                                       | Probabilité | Impact | Mitigation                                          |
|--------------------------------------------------------------|-------------|--------|------------------------------------------------------|
| LIFX ferme/restreint son API cloud                           | Faible      | Moyen  | Réversibilité vers Shelly (~10 lignes à changer)     |
| Wi-Fi domestique coupé                                       | Moyen       | Faible | Best-effort assumé, fallback Slack toujours présent  |
| Datadog change le format de ses webhooks                     | Très faible | Faible | Payload est templaté côté Datadog, pas imposé        |
| Cloudflare Python Workers cassent (encore en open beta)      | Faible      | Faible | Fallback JS Worker équivalent (~25 lignes)           |
| Saturation rate-limit LIFX (60 req/min)                      | Très faible | Faible | Dédoublonnage KV si besoin                           |
| Mauvais réflexe d'abonner la lampe à trop de monitors        | Élevé       | Moyen  | Discipline : seuls les monitors taggés `alert_lamp:true` |

---

## 10. Décisions techniques structurantes

| # | Décision                                          | Alternative écartée            | Justification courte                                                   |
|---|---------------------------------------------------|--------------------------------|------------------------------------------------------------------------|
| 1 | Ampoule LIFX Color A60                            | Hue                            | Pas de bridge à 50 €, API REST directe, OAuth inutile                  |
| 1 | Ampoule LIFX Color A60                            | Tapo L530E                     | CVE récurrents + cloud chinois + pas d'API publique                    |
| 1 | Ampoule LIFX Color A60                            | WiZ                            | Pas d'API cloud publique, UDP local incompatible Worker                |
| 1 | Ampoule LIFX Color A60                            | Shelly Duo RGBW                | LIFX plus mature côté effets natifs `pulse`/`breathe`. Shelly reste plan B EU.|
| 1 | Ampoule LIFX Color A60                            | Govee                          | Cloud chinois (même catégorie de doute que Tapo)                       |
| 2 | Cloudflare Worker (Python)                        | AWS Lambda                     | Free tier plus généreux, déploiement plus simple, edge mondial         |
| 2 | Cloudflare Worker (Python)                        | Worker JS                      | Préférence personnelle Python. Fallback JS si beta instable.           |
| 3 | Webhook Datadog natif                             | Polling API Datadog            | Push > pull, latence et coût meilleurs                                 |
| 4 | Header `X-Webhook-Token`                          | mTLS, signature HMAC           | Simplicité acceptable au regard de l'enjeu (lampe qui clignote)        |

---

## 11. Annexes

### A. Sélecteurs LIFX utiles

| Sélecteur            | Effet                                            |
|----------------------|--------------------------------------------------|
| `all`                | Toutes les ampoules du compte                    |
| `label:Alert`        | Ampoule(s) nommée(s) `Alert` dans l'app LIFX     |
| `group:Office`       | Toutes les ampoules du groupe `Office`           |
| `id:d073d5...`       | Une ampoule spécifique par MAC                   |

### B. Variables Datadog disponibles dans le webhook

| Variable               | Exemple                                  |
|------------------------|------------------------------------------|
| `$ALERT_TYPE`          | `error`, `warning`, `success`, `info`    |
| `$ALERT_TRANSITION`    | `Triggered`, `Recovered`, `Re-Triggered` |
| `$ALERT_ID`            | `1234567`                                |
| `$EVENT_TITLE`         | `[Triggered] API p95 > 500ms`            |
| `$EVENT_MSG`           | Le corps complet du monitor              |

### C. Liens de référence

- LIFX HTTP API : https://api.developer.lifx.com/
- Cloudflare Workers (Python) : https://developers.cloudflare.com/workers/languages/python/
- Datadog Webhooks : https://docs.datadoghq.com/integrations/webhooks/