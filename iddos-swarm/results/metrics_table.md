# Step 6 — before/after metrics

Same latency attack (5000 ms), 90s attack window, /work sampled at 5.0/s.

| Scenario | Stack | Attack | Availability | Restarts | MTTR (s) | TTD (s) |
| --- | --- | --- | --- | --- | --- | --- |
| baseline | vulnerable | no | 100.0% | 0 | — | — |
| vulnerable_attack | vulnerable | yes | 21.0% | 2 | 13.0 | 17.7 |
| mitigated_attack | mitigated | yes | 100.0% | 0 | 0.2 | — |

- **Availability** — share of `/work` requests returning 200.
- **Restarts** — web task restarts during the attack window.
- **MTTR** — seconds from toxic removed to web healthy again.
- **TTD** — seconds from attack start to the detector's first alert (`—` = no alert, i.e. no storm to detect).
