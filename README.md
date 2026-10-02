# hermes-thread

Session-scoped ask tracking for Hermes Agent.

Captures every ask you make in a session, groups follow-ups under a parent,
and renders them above the composer with live strike-through as they resolve.

## Design

- **Capture** — `post_llm_call` hook, off the latency path. Enqueues only;
  never makes a network call in the hook body.
- **Filter** — deterministic stage-1 noise drop (banners, notifications,
  duplicates, bare acks). Free; dropped 81 of 149 messages on real history.
- **Classify** — `thread_classify` auxiliary task on a cheap model, given the
  message plus the current ask list.
- **Store** — `~/.hermes/thread.db`.
- **Render** — `composer.top` plugin contribution area.

## Three-state attention model

| state | behaviour |
|---|---|
| CURRENT | exactly one; default target for new messages |
| OPEN | scanned only on a subject-change cue |
| COMPLETED | ignored unless the user explicitly reopens |

## License

MIT — see [LICENSE](LICENSE).
