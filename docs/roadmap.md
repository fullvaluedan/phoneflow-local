# Next steps

Implemented: bounded persistent worker, explicit app packages, combined
navigation and observation, per-device lock, optional installed Artemis
observation adapter, full/cropped evidence, per-account ledger, attempt versus
verified-action accounting, queue expiry, stale-observation guards and a stdio MCP connector with native
image responses and coordinate mapping. Four five-minute browse intervals were
exercised, with interruptions recorded in validation.

Priorities:
1. Benchmark helper and ADB observations over the same screens and measure total
   assistant latency, not just device command time. Record cold versus warm.
2. Validate selectors separately for feed, search, video, carousel and comments
   in each app. Record app versions and reject changed layouts. Currently these
   surfaces require assistant confirmation; no automatic screen classifier.
3. Add a transport-neutral observation/action interface before wiring another
   backend. Compare Mobile Next mobile-mcp as an existing MCP transport.
4. Measure the delivered MCP tools in additional assistant hosts. Native text
   and image delivery is implemented and verified through a stdio client;
   reconnect an existing host before expecting newly registered tools.
5. Add content-region OCR or short video samples for context when accessibility
   data is incomplete. Do not use pixel-change detection on a playing video as
   proof that navigation succeeded.
6. Migrate old logs only after confirming account identity and the counting
   definition. Preserve uncertainty rather than silently importing totals.
7. Add an independent watchdog/legacy-controller interoperability for stronger
   deadlines and ownership. Current locks protect PhoneFlow workers only.

No benchmark-based speed multiplier or complete four-app workflow claim yet.
