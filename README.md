# PhoneFlow

Local Android tools for an assistant that already runs in your chat or IDE.
The assistant makes contextual decisions; PhoneFlow executes bounded commands
and returns structured observations. There is no model client or API key in
PhoneFlow. Your assistant host has its own access requirements and usage limits.

**Prototype:** TikTok, LinkedIn, Facebook and Instagram package profiles are
included. They are observation/navigation profiles, not guaranteed end-to-end
social workflows. App layouts, account identity and content still need inspection.

```text
Your assistant: understands content and chooses the next action
     |
PhoneFlow: session queue, deadlines, device lock, evidence and ledger
     |
ADB: taps, swipes, keys and screenshots
     + optional installed Artemis helper: atomic screenshot + UI tree
```

## Start

Requires Python 3.10+, Android platform-tools, and an authorized USB-debugging
device. Install Pillow only if using cropped screenshots. The optional Artemis
adapter uses the Python environment of an existing configured Artemis checkout.
It does not install a helper APK or start an Artemis AI task.

Run from this directory. Replace the device and account placeholders with
verified values. ADB must be on PATH, or pass `--adb /absolute/path/to/adb`.

```sh
python phone_flow.py start --serial DEVICE --app tiktok --account ACCOUNT --seconds 420 --session sessions/example
python phone_flow.py status --session sessions/example
python phone_flow.py call --session sessions/example --request-file examples/observe.json
python phone_flow.py stop --session sessions/example
```

The start command returns immediately. Wait for `status: running` before calls.
Use a new session folder each run. Sessions are browse-only by default.
Launch is explicit: submit `examples/launch.json`. It may open the app's last
screen; it does not assume the current screen is a feed or a particular account.

Optional helper backend (paths depend on your installation):

```sh
python phone_flow.py start --serial DEVICE --app tiktok --account ACCOUNT --seconds 420 --session sessions/helper-example --artemis-repo /path/to/artemis --artemis-python /path/to/artemis/.venv/bin/python
```

On Windows the Artemis interpreter is usually `.venv/Scripts/python.exe`.
Helper startup has an initial import/attach cost. The bridge process stays warm
for the session. Errors fall back to ADB observation and are returned explicitly.
No helper credentials or transport tokens are printed by PhoneFlow.

## Commands

Requests are JSON objects. Call results contain `ok` and either `result` or
`error`. Observation IDs expire after 45 seconds for actions; observe again
when stale. All coordinates and crop boxes use original screenshot pixels.

| Operation | Required fields / behavior |
| --- | --- |
| `launch` | Opens configured app; returns observation |
| `observe` | `mode`: `auto`, `image`, `text`, or `both`; optional `crop: [x1,y1,x2,y2]` |
| `next` | Latest `observation`, confirmed `surface`: `feed`, `video`, `carousel`; swipe + settle + observation |
| `back` | Latest `observation`; Back + observation |
| `tap` | Latest `observation`; exact `selector` or `xy`; returns observation |
| `type` | Latest `observation`, `text`, `purpose: search/comment`; field must already be focused; optional `submit_search` |
| `hold` | `seconds` 0..60; waits locally, no model round trip per second |
| `review` | Latest `observation`, stable `post` label; records an assistant-reviewed post |
| `verify_action` | `attempt`, latest post-action image `observation`, `success: true`, `evidence_note` |
| `summary` | Per-app, per-account review and verified-action totals |

Example: after inspecting an observation, advance a video:

```json
{"op":"next","observation":"ID_FROM_LATEST_RESULT","surface":"video","mode":"image"}
```

Exact selector example:

```json
{"op":"tap","observation":"ID_FROM_LATEST_RESULT","selector":{"content-desc":"Back"},"action":"navigate"}
```

Navigation coordinates must be grounded in the latest image. Do not assume the
same button position across apps or between feed, search, video and comments.

`auto` uses images first for TikTok/Instagram. LinkedIn/Facebook try text first,
falling back to an image for sparse trees or an unexpected foreground app.
Accessibility data is always labeled freshness-unverified. Request `image` or
`both` to understand video/image content, to confirm identity, or before any
engagement. Atomic capture reduces timing mismatch; it does not prove the app's
accessibility labels accurately describe the video.

## Engagement accounting

Enable only actions the user authorized using `--allow like save follow comment`.
These are tool conventions, not a security boundary: a generic navigation tap
can affect any visible control. The assistant must honor authorization and stop
at login, verification, CAPTCHA, permission or restriction prompts. Prompt
detection is a limited text heuristic, not a comprehensive classifier.

Record a reviewed post before engagement. Label an engagement tap with
`action: like/save/follow/comment` and the matching `post`. A tap is recorded as
an attempt. The assistant must inspect the resulting image and separately call
`verify_action` before it contributes to successful-action totals. This is an
assistant assertion backed by evidence, not automatic visual recognition.
Existing selected controls must never be toggled blindly. Uncertain attempts
must be inspected instead of retried.

The ledger stores reviewed exposures, unique post labels and verified actions
separately for each app/account. It does not import historical text reports,
infer actual platform views or enforce engagement percentages. Percentages and
eligible content are policy decisions for the assistant, not mandatory quotas.
Comment composition and submission remain separate inspected actions.

## Timing and concurrency

The worker keeps Python/session state alive. ADB itself already uses a persistent
server; this does not replace ADB with a new low-level USB transport.

An OS lock prevents two PhoneFlow workers from owning the same serial, even
across separate checkouts on the same host. Older ADB scripts and Artemis runners
do not use this lock. Stop them first. `--legacy-workspace` checks unexpired
legacy timer files in a nominated workspace as an additional precaution.

At expiry or stop, the worker sends Wake and Home and records cleanup status.
This is best-effort: an in-flight command may delay cleanup, a USB disconnect
can prevent it, and killing the host process prevents this cleanup path.
Queued requests expire. After a call times out, inspect its returned result path
before resubmitting any mutation. Stop is checked during a local hold.

The worker sends Wake periodically while running, without changing display
settings. It does not unlock a secured device. Stop it when finished.

## Development

```sh
python -m unittest discover -s tests -v
```

Runtime evidence, accounts, ledgers, screenshots, session folders and local
configuration are ignored by Git. Do not add them when publishing. Unit tests
cover guards/accounting and do not operate a real device. Live UI verification
must start with device exploration; never invent an app interaction path.

See [research](docs/research.md), [validation](docs/validation.md) and
[next steps](docs/roadmap.md). This is a CLI prototype; an MCP server and
automatic content recognition are not implemented.
