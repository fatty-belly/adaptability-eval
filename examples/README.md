# Task examples

These are the original benchmark instructions for four task families. The
multi-turn version reveals one request at a time. The direct version asks for
the final behavior in one request from the same initial repository.

## Mini compiler closures

**EvoCodeBench · 2 turns · `legacy-003`**

The original compiler contract gives each closure a scalar snapshot. The
follow-up asks for shared lexical bindings so a setter and getter created
together can observe each other's updates, even after the enclosing function
returns. The direct request specifies shared capture as part of the language
contract from the start.

[Turn A](legacy-003/adapt/steps/a/instruction.md) ·
[Turn B](legacy-003/adapt/steps/b/instruction.md) ·
[Direct B](legacy-003/direct-b/instruction.md)

## Emoji-Process offsets

**NL2Repo · 2 turns · `new9-006`**

The library initially reports positions as Python string indices. Browser
clients need JavaScript-compatible offsets, so the follow-up changes existing
APIs to count UTF-16 code units. In `A😀B`, the emoji span changes from
`[1, 2)` to `[1, 3)`. The direct request defines the browser-compatible
coordinate system from the start.

[Turn A](new9-006/adapt/steps/a/instruction.md) ·
[Turn B](new9-006/adapt/steps/b/instruction.md) ·
[Direct B](new9-006/direct-b/instruction.md)

## Dungeon lighting

**SWE-chat · 3 turns · `sc-p03`**

The user starts by asking for a rules-owned `LightEmitter`. They then see a
boundary problem and ask the agent to infer lighting from object identities,
materials, and states. They reconsider and restore a canonical emitter for
fixed decorations while keeping reactive lighting on its existing paths.
The direct request describes the final architecture as one request.

[Turn 1](sc-p03/adapt/steps/a/instruction.md) ·
[Turn 2](sc-p03/adapt/steps/b/instruction.md) ·
[Turn 3](sc-p03/adapt/steps/c/instruction.md) ·
[Direct final](sc-p03/direct-final/instruction.md)

## qutebrowser diagnostics

**SWE-Journey · 18 turns · `sj-m-04`**

The sequence starts with more useful Qt object descriptions, then changes how
the RAM log retains and exports records. Later requests add privacy redaction
across diagnostic surfaces. The final turn makes redaction the default while
keeping an explicit raw mode for local debugging.

[All 18 turns](sj-m-04/adapt/steps/) ·
[Turn 1](sj-m-04/adapt/steps/step-01/instruction.md) ·
[Turn 11](sj-m-04/adapt/steps/step-11/instruction.md) ·
[Turn 18](sj-m-04/adapt/steps/step-18/instruction.md) ·
[Direct final](sj-m-04/direct-final/instruction.md)

## Run these examples

The complete Harbor packages include environments, reference solutions and
verifiers. Follow the [dataset download and preparation steps](../README.md#install-and-download),
then use the family IDs to select these examples.

```bash
python -m evaluation.run --data /data/benchmarks/adaptability-harbor \
  --run-dir /data/runs/adaptability-examples --arms baseline,full \
  --include legacy-003 new9-006 sc-p03 sj-m-04
```
