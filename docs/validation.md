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

## Four-platform and MCP validation update

24 unit tests passed on the existing Python 3.12 environment with MCP 1.29.0
and Pillow. New cases cover image mapping/crop origin, session-path isolation,
selector region conflicts, Windows transient sharing failures, blocking prompts,
scroll freshness and the one-time browse timer. The installed SDK emits a
nonfatal Pydantic annotation warning; protocol initialization and tool calls work.

A real stdio MCP client exercised start, launch, inline images, navigation,
observation, review, status, result/error handling and stop on the physical phone.
The following intervals used browse-only sessions, with no likes, saves,
follows, comments, applications or messages. Times are Asia/Taipei, 2026-10-20.

| Platform | Bounded interval | Result |
| --- | --- | --- |
| TikTok | 21:22:33–21:27:33 | Video navigation and visual review; pauses for reasoning |
| Instagram | 21:30:26–21:35:26 | Home feed scrolling after user-authorized notification denial |
| Facebook | 21:39:33–21:44:34 | Home feed scrolling; setup included closing an accidentally opened story |
| LinkedIn | 21:47:21–21:52:21 | Browsing with search/filter recovery; not uninterrupted scrolling |

Each timer ended within about 0.33 seconds of its five-minute deadline and
recorded Home cleanup. This is a sample, not a hard real-time guarantee.
LinkedIn encountered a system update prompt during preflight (no update installed)
and a stale accessibility selector opened a job preview during navigation.
Back closed it. Selector taps now require an image-grounded region and reject
conflicting node positions. The regression test verifies that rejection.

A subsequent short TikTok smoke check of the final code verified launch,
pre-scroll inspection, a visible video transition and native image delivery,
then explicit stop/Home. Its warm helper captures were 344 and 203 ms; full
launch tool response was 2.4 seconds and next response 2.7 seconds, excluding
assistant reasoning. These are individual samples, not throughput benchmarks.

The earlier limitations still apply: no automatic account/content recognition,
no validated engagement workflows, and no unattended four-app classifier.
Runtime screenshots, account identities and local configuration are not published.

## Android 16 rotation regression - 2026-10-21

During a repeat browsing run, LinkedIn opened in landscape. `dumpsys input`
reported rotation in `Viewport INTERNAL ... orientation=...` rather than the
older `SurfaceOrientation` field. The controller now recognizes the default
display viewport, keeping swipes and tap bounds aligned with rotated screens.
25 unit tests pass, including the new landscape viewport regression. Live
LinkedIn scrolling was verified after restarting its full five-minute timer.
