# SHA-pinned remediation review report

These dispositions are independent code-review findings, not GitHub review approvals or CI
results. The fork has no hosted checks configured.

| PR | Reviewed head | Disposition | Key evidence and limit |
| --- | --- | --- | --- |
| [#4](https://github.com/samuelczhao/superset/pull/4) | `d6394296de8682e5ead171f20b4167bee7b7971c` | Accepted candidate | Delegates database child serialization to the canonical dataset exporter; no blocking defect found. A stale skipped-test marker and broader integration coverage remain follow-ups. |
| [#5](https://github.com/samuelczhao/superset/pull/5) | `0c3fc7e5d1d9c9fc708551855d31e3e863ca146b` | Rejected and closed | The command still failed before or during association creation on current SQLAlchemy/dialect paths; the repair test could observe stale ORM state. Findings became issue #7. |
| [#6](https://github.com/samuelczhao/superset/pull/6) | `a5f43230252629a9533265d8aa7f8078e87cc439` | Accepted candidate | Instance-local tag-export state removes abort and concurrency leakage. Combined-tag content and literal interleaving tests are optional gaps; integration DB setup prevented independent integration execution. |
| [#8 initial](https://github.com/samuelczhao/superset/pull/8) | `6f21b96f728e165d76364765e503606497d96beb` | Amendment required | Unexpected custom/editor rows using a reserved favorite-tag name could receive the wrong association. Review required an explicit collision and type-filtered joins. |
| [#8 amended](https://github.com/samuelczhao/superset/pull/8) | `ce011364c0a49ce847a18aeef99ba1a1f3236ae4` | Accepted for take-home | Corrected SQLAlchemy 2 calls, portable joins, transaction handling, exact-name collisions, and test reloads. A narrow repeatable-read concurrency limitation remains documented. |

“Accepted candidate” means no blocking correctness issue was found at the pinned head within the
take-home scope. It does not mean merged, production-approved, or CI-confirmed.
