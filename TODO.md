# TODO

- Add a versioned YT Library host capability for authenticated YouTube
  operations, including safe temporary cookie handling, proxy use, request
  policy, and cancellation.
- Extend the host planning contract with livestream identity and broadcast
  observation fields described in `docs/design.md`.
- Add distinct active-capture and replay worker processes after those host
  capabilities exist.
- Define and implement durable JSONL action ingestion, normalized query models,
  capture revision handling, and retention policy.
- Add browser and detail-page surfaces only after capture and replay behavior is
  proven against local fixtures.
