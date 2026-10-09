# Security and data-safety notes — through Sprint 8

- UI does not import/open SQLite, Worker implementations or concrete Engine adapters.
- Mutating UI commands use durable Core command semantics; the UI projection is non-authoritative.
- Remote/projected titles and inputs are sanitized for control/bidi characters and rendered as
  QML PlainText rather than AutoText/rich text.
- Persisted URL display input removes userinfo/fragments and redacts common sensitive query keys.
- Core/Worker bootstrap secrets remain off argv/environment as established in Sprint 3.
- DirectHTTP continues to strip ambient/secret headers and uses the Sprint 2 PREPARED-before-file
  commit boundary.
- The Sprint 5 in-process UI bridge is development-only and must not be packaged as the production
  UI/Core architecture.
- Production fault injection and QA trust roots remain prohibited from release artifacts.

- Gate 6.5 marks every TransferDescriptor EPHEMERAL_ONLY and provides a diagnostic view that strips
  URL userinfo/query/fragment, all header values and credential grant identifiers.
- Persistence is architecture-tested against importing engine runtime contracts/concrete engines.
- Managed engines may report OPAQUE/BEST_EFFORT control; security/resource decisions must not assume
  exact internal connection counts when the engine cannot prove them.
- Future updater SUCCESS requires candidate identity/health + current-pointer commit evidence;
  download progress, filename checks and detached-helper launch are never trust evidence.

- Sprint 8 Browser Assist is Static-fallback only, Worker-owned and non-persistent; browser-owned downloads are disabled.
- Playwright request routing uses `service_workers="block"` so ordinary page requests cannot disappear behind a Service Worker interception layer.
- Public roots cannot derive localhost, private, link-local, multicast, reserved or mixed public/private DNS destinations.
- Private/LAN roots require explicit opt-in and are confined to their exact origin; simply typing a URL is not sufficient private-network consent.
- Web/Browser `TransferDescriptor` scope is enforced again during DirectHTTP redirects to prevent a safe-looking candidate from redirecting into a private target.
- CSP is not bypassed and persistent browser profiles/storage state are not used.

- Browser Assist blocks popup windows and WebSockets by default, and aborts known image/media resource requests after observing their URL so the browser cannot become an ungoverned second transfer engine.
