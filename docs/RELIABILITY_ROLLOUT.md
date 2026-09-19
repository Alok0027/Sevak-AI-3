# Reliability changes: deployment and operating limits

## Approved workflow

- Assessment creates a patient-message draft; it sends no patient text.
- The ASHA opens **Profile → message icon → Patient notifications**, selects WhatsApp or SMS, reviews the recipient and exact outgoing text, and confirms patient consent before approval.
- One action can be approved only once. There is no automatic second-channel send.
- ANM (own sub-centre) or BMO resolves a visit's risk with a required note. Completing an ASHA follow-up does not resolve the risk. Historical risk classification is retained; a resolved visit cannot be rewritten using risk override.

## Deployment order — not performed by the code change

1. Back up the database and encryption key. Verify recovery in a disposable environment.
2. Deploy backend first. Startup creates `visit_requests`, `notification_outbox`, and `risk_resolutions` using the existing create-all bootstrap. No existing tables are dropped. Production installations should incorporate these new tables into their managed migration process.
3. Existing plaintext backend sync payloads remain readable but need the explicit `python -m scripts.encrypt_existing_data` backfill. This command changes stored data: review and back up before running it. New sync payloads are encrypted immediately.
4. Rebuild/install the mobile app (native secure-storage dependency; hot reload is insufficient), then deploy the dashboard. Android now requires API 23+. Validate iOS signing/keychain entitlement on a device.
5. Provision an independent scheduler, sharing the API's database, encryption key and provider configuration. Run `python -m scripts.process_notifications` from `backend` once per minute. This command sends messages when real providers are configured. Do not run it against real data as a smoke test. No paid service or scheduler is activated by these source changes.
6. Retain existing 48-hour escalation timing and ANM-first/BMO-fallback routing. Supervisor dispatch uses SMS; it stays pending if real SMS is not configured. This is not an immediate-ANM/48-hour-BMO two-stage policy.
7. Verify Meta's configured `followup_reminder` / `hi` body matches the checked-in template text exactly. Other template names/languages are blocked until their verified previews are implemented. Approval is an ASHA attestation of consent, not a complete consent-management system.

## Retry and crash semantics

- Current mobile submissions and queue retries share a stable request ID. A database uniqueness constraint arbitrates concurrent submissions. The visit, actions, flag and encrypted response are committed together; subsequent retries replay that response.
- Reusing an ID with different clinical content is rejected. Older external clients without an ID retain legacy behavior; upgrade them before claiming duplicate protection for every client.
- A process crash after claiming a visit but before committing its result leaves a pending receipt. It is **not automatically retried**. Inspect the receipt, confirm the original process is stopped and no committed result exists, and recover through a reviewed database operation. No unsafe automatic stale-claim takeover is provided.
- Outbox workers claim messages atomically before provider I/O. Connection failures that occur before sending retry up to five attempts with exponential backoff. Uncertain outcomes (including read timeouts) become `needs_review`; worker crashes are marked for review after 15 minutes on a later scheduler tick. Do not resend until provider records establish that no message was accepted.
- `accepted` means provider acceptance, **not delivery or read confirmation**. Signed provider-webhook reconciliation and a recovery-console UI are not included. A scheduler tick that never runs cannot recover its own crash.
- Provider changes after approval block delivery; do not silently redirect approved messages to another provider. An already in-flight message cannot be recalled when a risk is resolved.

## Local storage

- Session identity/token moves from SharedPreferences into platform secure storage. Legacy preferences are removed only after a successful secure write. Logout removes the session but retains the queue encryption key so pending visits are not destroyed.
- Queue clinical payloads use AES-256-GCM; the key lives separately in platform secure storage. Existing plaintext rows are encrypted before queue reads return. Migration errors stop access rather than discard records. SQL metadata (worker ID, queue ID, timestamps, type) remains plaintext.
- Migration enables secure deletion, checkpoints SQLite's WAL and vacuums the database. This cannot erase old OS/cloud backups or guarantee forensic erasure of flash storage. Android application backup is disabled for future backups.
- Acknowledged queue rows are deleted; unresolved records remain. Loss of the device key makes its encrypted queue unreadable: never clear secure storage as a troubleshooting step while pending visits exist.
- Native recording temporary files and device-level backup/keychain behavior still require a physical-device validation pass. This is not a claim of whole-device encryption or protection on a compromised device.

## Verification and rollout gate

Automated tests use an isolated database, fake providers and mocked secure storage. They do not send live SMS/WhatsApp or validate clinical correctness. Before real patient use, exercise app upgrade with pending visits, force-close/restart during upload, offline login, keychain access, provider outages and scheduler monitoring on representative Android/iPhone hardware. Do not treat passing unit tests as clinical validation or a measured load-capacity guarantee.
