# ADR 0018 — Static-first Web resolution with constrained Browser Assist

## Status
Accepted for Sprint 8.

## Context
Unknown web pages require more than gallery-dl/yt-dlp coverage, but making a full browser the default
resolver would add remote-JavaScript execution, persistent browser state, uncontrolled network
activity and a second download owner to the normal path.

## Decision
1. Worker runs deterministic Static Web discovery first.
2. Playwright Browser Assist is invoked only when Static discovery yields no usable media.
3. Browser Assist uses an installed Microsoft Edge channel, a fresh non-persistent context,
   `accept_downloads=False`, `service_workers="block"`, and request routing.
4. Browser popups and WebSockets are blocked by default; common image/media requests are observed and aborted before body transfer.
5. Browser/network observations are normalized into ordinary V10 `NormalizedItemDescriptor` /
   ephemeral `TransferDescriptor` objects. Browser Assist never owns durable download completion.
6. Derived destinations are subject to network-scope checks. Public pages cannot derive localhost,
   RFC1918, link-local, multicast, reserved or mixed public/private DNS targets.
7. Private/LAN roots require explicit opt-in and are then restricted to the exact root origin; public
   destinations remain permitted.
8. DirectHTTP re-checks Sprint-8 network scope during redirects so the security decision survives the
   resolver -> transfer handoff.

## Consequences
- JS/browser cost and attack surface stay off the normal path.
- Browser fallback remains compatible with existing Scheduler/Resume/FileCommit semantics.
- Service Worker dependent sites may behave differently in Browser Assist. This is deliberate: exact
  request mediation has priority over transparent service-worker compatibility in the fallback mode.
- DNS-rebinding and Edge enterprise-policy behavior still require Windows live fault gates.
