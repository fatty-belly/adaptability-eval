I need clients to retrieve pipeline step results by name. Change full Nexus run records from the `steps` array to schema version 2 while keeping the pipeline behavior and existing saved runs working.

## Full run representation

Every full run object emitted by `nexus pipeline run <config.json>`, `nexus pipeline status <run-id>`, `nexus pipeline list` (each entry) or `nexus pipeline resume <run-id>`, and every newly saved or migrated `/tmp/nexus/runs/<run-id>/run.json`, must contain:

- `schema_version: 2`.
- `steps`: a JSON object mapping each exact step name to its complete per-step record, retaining the record's `name` field.
- `step_order`: a JSON array containing every step name exactly once, in configuration order. Object key order has no meaning.

Replace the array representation by default on these commands; there is no legacy-output flag. For example, running:

```json
{"name":"schema-demo","steps":[{"name":"zeta","type":"shell","command":"printf first"},{"name":"alpha","type":"shell","command":"printf second","depends_on":["zeta"]}]}
```

must emit `steps.zeta.output == "first"`, `steps.alpha.output == "second"` and `step_order == ["zeta","alpha"]` in run output, status output and saved records.

## Existing records and migration

Continue reading unversioned `run.json` files whose `steps` are arrays as legacy version 1, alongside version 2 records in the same store. On successfully loading a legacy run through status, list, history or resume, derive `step_order` from its array and atomically replace that `run.json` with version 2. Legacy records must remain discoverable even when they are present only in the run directory and not in an index.

Conversion must be idempotent: a second status request must leave the converted record unchanged. Read commands must not rewrite already-versioned run files. Preserve the run ID, status, timestamps, all run and per-step values, artifact paths and contents, and experiment links. Loading or migration must never execute commands or create experiments.

## Behavior to retain

Keep `checkpoint.json` and `manifest.json` formats intact. Resume must accept both legacy records with their existing checkpoints and migrated records, skip the checkpoint's already-completed steps, and execute remaining work with the same pipeline semantics, including variables, references, conditions, retries and `allow_failure`.

Artifact lookup, history filters and deletion must work for both versions; deleted runs must not reappear in list, history or status. All other run and step fields retain their values and semantics, including outputs, timing, `retry_history`, warnings, variables, tags, descriptions, artifacts and experiment IDs.

Pipeline configuration steps and dry-run plan steps remain arrays. History keeps its summary format and its status and tag filters. Preserve all DAG, execution, validation, tracking and CLI behavior apart from the full-run steps representation. Keep /usr/local/bin/nexus built from /app.
