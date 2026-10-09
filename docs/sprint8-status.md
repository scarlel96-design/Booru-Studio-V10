# Sprint 8 Status — Static Web / Browser Assist / Postprocess Security

## Result
SOURCE SCOPE COMPLETE pending final archive seal.

## Implemented
- Static HTML resolver using bounded parsing of `img`, `video`, `audio`, `source`, OpenGraph/Twitter
  media metadata, `srcset`, poster and media preload/prefetch links.
- 4 MiB HTML ceiling, 5-redirect ceiling and 2,000-candidate ceiling.
- explicit public/private network-scope model with mixed DNS answer rejection.
- private/LAN roots disabled by default and available only through explicit opt-in, same-origin only.
- Worker-owned Playwright 1.62.0 / installed Edge Browser Assist boundary.
- fresh non-persistent browser context, `accept_downloads=False`, Service Worker blocking and routed
  request authorization.
- Browser DOM/network observations revalidated before handoff; known image/media requests are observed then aborted so Browser Assist does not duplicate the final DirectHTTP transfer.
- Browser popups and WebSockets are blocked by default to avoid ungoverned side channels.
- Static-first -> Browser-fallback orchestration; Browser is not launched when Static discovery works.
- `WEB_PAGE` collection semantics for multi-media ordinary web pages.
- signed/temporary candidate URLs remain ephemeral and do not enter durable collection/item state.
- DirectHTTP redirect-time network-scope enforcement for Sprint-8 descriptors.
- FFmpeg stream-copy remux + ffprobe structural verification for container-only postprocess.
- Windows QA runtime smoke for exact Playwright pin + installed Edge + private-target blocking.

## Deferred
- UI detail/presentation refinement: Sprint 9.
- Native Supervisor, Job Object and production QLocal validation: Sprint 10.
- Frozen packaging/installer: Sprint 11.
- App/Engine Pack updater: Sprint 12.
- migration/reliability fault hardening: Sprint 13.
- Windows live-browser/DNS-rebinding/enterprise-policy soak and RC: Sprint 14.
