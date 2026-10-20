# Existing projects and reuse decision

Reviewed 2026-10-20. These are upstream descriptions and source inspections,
not independent accuracy benchmarks. License labels below were checked in the
repositories; examine the exact files and notices before vendoring code.

| Project | Relevant capability | Decision |
| --- | --- | --- |
| [google/artemis](https://github.com/google/artemis) | Android agent, accessibility helper, combined screenshot/tree, verified checkpoints and trace history; Apache-2.0, with separately attributed third-party files | Reuse the installed helper through its observation client. Keep autonomous model orchestration optional. |
| [mobile-next/mobile-mcp](https://github.com/mobile-next/mobile-mcp) | Existing MCP tools connecting the current assistant to physical/simulated Android/iOS, with accessibility snapshots and screenshot fallback; Apache-2.0 | Closest ready-made connector to evaluate before building our own MCP layer. |
| [droidrun/mobilerun](https://github.com/droidrun/mobilerun) | Former droidrun repository now redirects here; agent framework with device tools, UI state, screenshots and tracing; MIT | Learn separation of agent and device tools. An LLM-agnostic agent does not itself remove provider usage charges. |
| [chukfinley/droidrun-mcp-server](https://github.com/chukfinley/droidrun-mcp-server) | Smaller bridge using Droidrun Portal's accessibility tree and indexed taps; MIT | Useful minimal connector reference. Its screenshot-free approach cannot supply visual video context by itself. |
| [openatx/uiautomator2](https://github.com/openatx/uiautomator2) | Python Android automation, selectors and UI inspection; MIT | Useful alternate backend. Check accessibility-service coexistence before enabling alongside Artemis helper. |
| [Genymobile/scrcpy](https://github.com/Genymobile/scrcpy) | USB screen streaming/control and recording; Apache-2.0 | Useful future frame transport; streaming faster does not remove model reasoning latency. |

## Why the hybrid

ADB is the transport and action mechanism. Artemis adds perception, agent
orchestration, recovery and verification. PhoneFlow adds a small session layer
while leaving content decisions with the assistant already in the host.
Neither screenshot streaming nor an accessibility tree makes understanding a
new video free or instantaneous.

The local Artemis source inspected exposes a helper manager and authenticated
loopback HTTP `/dump_xml` and `/snapshot?fields=xml` endpoints. The adapter uses
the installed manager with `provision=False` and reads those endpoints directly.
This avoids the general observation client's wake/display policy initialization.
It does not copy upstream modules or invoke
`mobile_run_task`, Planner, Operator, Checker or an LLM client. Upstream internals
can change, so this optional adapter needs version compatibility testing.

Current PhoneFlow implementation is original integration code, MIT licensed.
Artemis and other projects retain their own licenses. No upstream source or APK
is bundled. Future copied files need their original notices and attribution.

## What would reduce delay

Local combined commands eliminate intermediate model turns for predictable
transitions. The persistent helper bridge removes repeated Python imports and
helper attachment. Text observations can avoid sending a full image when the
screen is text-centric. Crops reduce the pixels supplied for verification while
retaining full local evidence. Each optimization has to be measured on the
same device and app state; none promises a percentage speed-up in advance.


## Connector evaluation

[Mobile Next mobile-mcp](https://github.com/mobile-next/mobile-mcp) already
provides an Apache-2.0 mobile connector. Its server source demonstrates indexed
element references, batched commands, cached device objects, resized screenshots
and action timing. PhoneFlow adopts the interface ideas of combined action plus
observation and explicit image mapping, without copying source. Mobile Next was
evaluated from source, not installed or benchmarked against this implementation.
PhoneFlow currently retains its bounded worker, ownership lock, evidence ledger
and existing Artemis helper. Broad blind action batches are intentionally absent
because app transitions and stale labels need inspection. No telemetry is sent.
The stdio adapter uses the installed stable MCP Python v1 SDK, pinned below v2.
