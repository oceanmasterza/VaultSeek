# Nicotine+ provider setup

VaultSeek's first real acquisition provider talks to an **installed Nicotine+ client**. VaultSeek does not speak raw Soulseek protocol — it uses one of two transports documented below.

See also [ARCHITECTURAL_UPDATE_001.md](ARCHITECTURAL_UPDATE_001.md) (ADR-0017) and `src/vaultseek/plugins/builtin/nicotine_plus/`.

---

## Prerequisites

1. Install and run [Nicotine+](https://nicotine-plus.org/) on the same machine as VaultSeek (Windows today).
2. Enable the Nicotine+ provider in **Settings → Acquisition** (`enabled: true`).
3. Choose a transport:
   - **HTTP** (recommended) — uses the community [api-nicotine-plus](https://github.com/sjluke/api-nicotine-plus) plugin
   - **Socket** — uses VaultSeek's NDJSON protocol on a local TCP port (default **22024**)

---

## Option A — HTTP transport (recommended)

1. Install **api-nicotine-plus** into Nicotine+ (follow that project's README).
2. Start Nicotine+ and confirm the HTTP API listens on port **12339** (default).
3. In VaultSeek **Settings → Acquisition**:
   - Transport: **HTTP**
   - API port: `12339`
   - API token: set if your api-nicotine-plus instance requires one

VaultSeek's `HttpApiRpcClient` maps search/download/status calls to the HTTP API.

**Limitation:** HTTP cancel may return `false` — cancelling an in-flight Nicotine+ download from VaultSeek may not work over HTTP until the API supports it.

---

## Option B — Socket transport (NDJSON)

Nicotine+ has no built-in socket RPC. Use VaultSeek's companion proxy, which accepts NDJSON on a local port and forwards to the HTTP API:

```powershell
python scripts/nicotine_plus_ndjson_proxy.py --listen 22024 --api-url http://127.0.0.1:12339
```

1. Start api-nicotine-plus inside Nicotine+ (port 12339).
2. Run the proxy script (keep it running while acquiring).
3. In VaultSeek **Settings → Acquisition**:
   - Transport: **Socket**
   - Socket port: `22024` (must match `--listen`)

Protocol details live in `src/vaultseek/plugins/builtin/nicotine_plus/rpc.py` (`LocalSocketRpcClient`).

---

## Troubleshooting

| Symptom | Check |
|---------|--------|
| Provider offline / connection failed | Nicotine+ running; api-nicotine-plus enabled; correct port/token |
| Search returns no results | Soulseek account connected in Nicotine+; search terms match job artist/album |
| Jobs stuck in `downloading` | Download folder permissions; Nicotine+ download queue; automation service running |
| Socket transport fails | Proxy script running; firewall not blocking localhost |
| Auto-acquire never starts | Score below threshold in Settings; job in `waiting_for_user` needs manual pick |
| Search / download fails silently | Check **Dashboard → Attention needed** — `acquisition_no_results` / `acquisition_failed` review items are created for NO_RESULTS, provider offline, and download/verify/import failures |

Acquisition jobs and states are visible on the **Acquisition** page. Background automation (`AcquisitionAutomationService`) polls downloads and schedules retries with exponential backoff. User-visible acquire failures also appear under **Dashboard → Attention needed**.

---

## Configuration reference (schema v9)

In `%APPDATA%\VaultSeek\config.json` under `acquisition.providers.nicotine_plus`:

| Key | Default | Purpose |
|-----|---------|---------|
| `enabled` | `false` | Connect provider at startup |
| `transport` | `socket` | `socket` or `http` |
| `socket_port` | `22024` | NDJSON listen port (socket transport) |
| `api_port` | `12339` | HTTP API port (http transport or proxy target) |
| `api_token` | `""` | Optional bearer token for HTTP API |

Global acquisition settings:

| Key | Default | Purpose |
|-----|---------|---------|
| `auto_acquire_threshold` | `0.90` | Auto-download when best score ≥ threshold |
| `auto_queue_jobs` | `true` | Queue jobs created by missing-media scan |
