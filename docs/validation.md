# Prototype validation - 2026-10-20

Environment: Windows, authorized physical Android 16 device. Runtime screenshots
and serial/account data remain outside this repository. No engagement was
performed by these smoke checks.

- 13 unit tests passed: expired queued actions, stale observations, wrong-app
  actions, unauthorized likes, duplicate attempts/reviews/verifications,
  evidence requirements, separate account totals, device lock exclusion and
  legacy timer detection.
- Artemis MCP hierarchy inspection confirmed the live LinkedIn search screen
  before test authoring. Artemis diagnosis later returned ready, with no active
  or queued agent tasks.
- Direct ADB path launched TikTok and captured both screenshot and hierarchy.
  The resumed TikTok screen said "List is empty"; no feed engagement was tested.
- The first persistent helper prototype timed out and fell back to ADB as
  designed. Its general observation client initialized wake/display policy.
  The revised adapter uses the installed helper manager and HTTP observation
  endpoints directly, with PhoneFlow owning session wake behavior.
- Revised helper snapshot sample: 266 and 594 ms, excluding interpreter import
  and attachment time. In the worker, warm LinkedIn helper snapshot took 218 ms;
  its full observation took 391 ms including foreground checking and file work.
  These are small samples, not average latency or an end-to-end speed benchmark.
- LinkedIn: launch and atomic observation succeeded. Focused search accepted
  "AI automation"; the captured state showed autocomplete/loading, so complete
  search-result navigation is not claimed.
- Facebook: launch and atomic observation succeeded; home feed was visible.
- Instagram: launch reached a notification permission prompt. A follow-up
  observation identified the permission-controller foreground. Stopped without
  choosing Allow or Don't allow. Full Instagram browsing is not validated.
- Timed worker expiry and explicit stop paths both recorded Home cleanup.

Not verified: complete app-specific search/feed/comment/follow workflows,
automatic verification of likes or comments, account detection, unattended
recovery after host process death, and a complete MCP integration. App profiles
and generic commands are implemented; they do not imply these workflows pass.

Recommended next measurement: same screen, same phone, repeated cold/warm ADB
and helper observations, with screenshot transport and model-turn latency
reported separately. Keep visual context checks for video/image content.
