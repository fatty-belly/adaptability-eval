Implement a pipeline engine for Nexus in /app so I can run complete ML workflows as directed acyclic graphs of steps that produce and consume typed artifacts. Preserve the existing model, experiment and dataset interfaces, and build the CLI as /usr/local/bin/nexus.

## Pipeline configuration

Pipeline definitions are JSON files with a `name`, optional `parameters` (string key-value pairs with defaults), a `max_parallel` limit (default 4), an optional `resource_limit` with `cpu` and `memory_mb` fields, and a `steps` array. Support `tags` as an array of strings and `description` as a string; copy both to the run output. If tags are unspecified, the run's `tags` must be `[]`, not absent.

Each step supports:

- `name`: unique within the pipeline.
- `type`: `shell` (runs a command), `train` (creates an experiment, runs a command and logs metrics), or `evaluate` (runs an evaluation command).
- `command`: the shell command to execute, with `${param_name}` substitution and the variable features below.
- `depends_on`: a list of step names that must complete first.
- `inputs`: artifact names consumed by this step, coming from a dependency's `outputs`.
- `outputs`: artifact names produced by this step.
- `resources`: optional `{"cpu": N, "memory_mb": N}`; a step's request must not exceed the pipeline's `resource_limit`.
- `timeout_seconds`: per-step timeout; 0 means no limit.
- `retry`: optional `{"max_retries": N, "backoff_base_seconds": N}` with exponential backoff.
- `condition`: an optional expression controlling whether the step executes, as described below.
- `allow_failure: true`: lets downstream dependents continue if this step fails.
- `capture_output`: a string or object for capturing stdout, as described below.
- `env`: an object such as `{"KEY": "VALUE", ...}` for step environment variables.
- `experiment_config` for `train` steps: `{"name": "...", "params": {...}, "metrics": ["..."]}`.
- `dataset_ref` for `evaluate` steps: a string reference.

## Validation and execution

Provide `nexus pipeline validate <config.json>`. Before execution, validate that:

1. Step names are unique.
2. There are no cycles; report the cycle path in the error.
3. Every dependency names an existing step.
4. Every input artifact has a producer that is a transitive dependency of its consumer.
5. No two steps produce the same output artifact name.
6. No step's resource requirements exceed the pipeline's resource limit.

Run pipelines with `nexus pipeline run <config.json> [--param key=value ...] [--max-parallel N]`. Merge CLI parameters over configuration defaults. Start steps as soon as all dependencies are satisfied, subject to `max_parallel` and resource limits: a step's requirements plus those of all currently running steps must not exceed the pipeline limit.

For `shell` steps, execute the command, capture combined stdout+stderr and track the exit code. For `train` steps, create an experiment through the existing tracker, run the command, and log each stdout line matching `key=value`, where value is a float, as a metric on that experiment. Mark the experiment completed on success or failed if the command fails. These experiments must appear in `nexus experiment list`. For `evaluate` steps, run the command and register output artifacts as type `metrics`.

If a dependency fails, its dependents fail with "dependency failed", unless the failed dependency has `allow_failure: true`; in that case its downstream dependents execute normally. A successful `allow_failure` step behaves like any other successful step. Steps whose conditions are false are marked `skipped` and treated as completed for dependency purposes.

If the only failures are steps with `allow_failure: true`, the overall run status is `succeeded_with_warnings`. If any step without `allow_failure` fails, the run is `failed`. Include a `warnings` array of the names of failed `allow_failure` steps in the run JSON, using an empty array when there are none.

Support retries with delay = `backoff_base_seconds ^ attempt` seconds. Each step record must always include a `retry_history` array, never null or absent. Each entry records one actual execution attempt with `attempt` (0-based) and `error` (the attempt's error message, or an empty string on success). A first-attempt success has one entry with attempt 0 and an empty error. A step without retries configured still has one entry for its single actual attempt. A step that never executes, such as one skipped by its condition or marked dependency-failed before running, has `retry_history: []`.

Print the full run JSON to stdout when `nexus pipeline run` completes or fails. Exit 0 on success and 1 on validation or execution failure.

## Variables, output capture and environment

Support both forms of `capture_output`:

- A string, `"<var_name>"`, stores the step's full trimmed stdout in that runtime variable.
- An object, `{"name": "<var_name>", "regex": "<pattern>"}`, stores only the first capture group of the regex match against stdout. If the regex does not match, the variable is not set.

Subsequent steps can reference captures as `${<var_name>}` in commands. A capture takes precedence over a pipeline parameter of the same name. If the producing step is skipped or fails, including failure with `allow_failure: true`, its capture is not set. A downstream command with an unresolved `${...}` token after substitution must fail with a clear error.

Support `${var:-default_value}` anywhere regular variable substitution works, including commands, conditions and captured variable references. Use the default only if the variable is not set by either parameters or captures; if it is set, use its actual value. Defaults cannot contain nested `${...}` references. After substitutions, including defaults, a remaining `${...}` token without a `:-` default is an unresolved variable error, with the condition and dry-run behavior described below.

Commands and conditions can reference an upstream step's result as `${steps.STEPNAME.status}`, resolving to `succeeded`, `failed` or `skipped` after that step completes.

Also support automatic output and timing references:

- `${steps.STEPNAME.output}` resolves to that step's trimmed stdout after successful completion. For a failed step, it resolves to an empty string.
- `${steps.STEPNAME.duration}` resolves to the step's wall-clock duration in seconds formatted to two decimal places, such as `"0.15"`. It is available for all completed steps, including failed and skipped steps; skipped steps have duration `"0.00"`.

Output and timing references work anywhere `${...}` substitution works, including commands, conditions, environment values and defaults such as `${steps.X.output:-fallback}`. Named `capture_output` variables work independently of `.output`: the automatic output reference uses raw trimmed stdout rather than the named or regex capture.

Set each step's `env` entries before executing its command. Environment values support `${var}` substitution using effective variables (parameters plus captures). Also expose parameters and captured output variables as environment variables prefixed with `NEXUS_PARAM_`; for example, `foo` becomes `NEXUS_PARAM_foo`.

Include a top-level `variables` map in the run JSON showing all resolved runtime variables from parameters and captures.

## Conditions

Support comparisons such as `${param} == value` and `${param} != value`, along with:

- `&&`: both subconditions must be true, for example `${mode} == prod && ${steps.validate.status} == succeeded`.
- `||`: at least one subcondition must be true, for example `${steps.test.status} == failed || ${steps.test.status} == skipped`.
- `contains`: the left side contains the right side as a substring, for example `${steps.check.output} contains PASS`.

`&&` binds tighter than `||`, so `A || B && C` means `A || (B && C)`. Only simple expressions with one level of mixing `&&` and `||` are required; parentheses and deeply nested expressions are not required.

If any unresolved `${...}` reference remains in a condition after substitution, evaluate the condition as false and skip the step rather than raising a runtime error. This includes forward references.

## Artifacts, checkpoints and persistence

Store run state, including checkpoints and artifacts, under `/tmp/nexus/runs/<run-id>/`. Pipeline run data must persist independently from the existing Nexus store so that `pipeline list` and `pipeline status` work across invocations.

Each artifact has `name`, `type` (`data`/`model`/`metrics`/`log`), `producer` step name, `path` and `size`. Write shell-step output artifacts to `<run_dir>/artifacts/<step_name>/<artifact_name>` with the step's stdout as content. After execution, `nexus pipeline artifacts <run-id>` prints the full manifest as JSON with a `lineage` map showing which steps consumed each artifact.

After each step completes, save `<run_dir>/checkpoint.json` containing completed step names, step statuses, artifacts and parameters. Use this checkpoint shape (other existing fields must survive updates): `{"run_id":"run-example","completed_steps":["first"],"step_statuses":{"first":"succeeded","second":"failed"},"artifacts":[],"parameters":{},"saved_at":"2026-01-01T00:00:01Z"}`. Failed unfinished steps remain outside `completed_steps` so resume retries them. The run record may identify its original configuration with `config_path`; load that file when no embedded configuration is present. An already-completed step keeps its existing JSON fields and values when resumed. `nexus pipeline resume <run-id>` reloads the checkpoint, skips already-completed steps and executes the remaining steps from where execution left off.

## Run records and status

Each run gets a unique ID and tracks its pipeline name, status (`pending`, `running`, `succeeded`, `failed` or `succeeded_with_warnings`), parameters and start/end times. Each per-step record includes status, timing, output, error, artifacts, experiment ID if any, retry count and the `retry_history` described above. Runs also include the variables, warnings, tags and description described above.

The run's `steps` field is a JSON array of per-step objects in configuration order, so `steps[0]` is the first configured step.

`nexus pipeline status <run-id>` prints the run as JSON. `nexus pipeline list` prints all runs as a JSON array.

## Planning and graph inspection

`nexus pipeline run --dry-run <config.json> [--param key=value ...]` validates the configuration, resolves static variables (parameters and defaults), evaluates conditions using available static variables and prints a JSON execution plan without executing anything. Captured variables exist only at runtime and must not be resolved during a dry run.

The plan is an object with a `steps` array of objects containing `name`, `type`, `resolved_command`, `status` and `depends_on`. Status is `"ready"` for steps that would execute, `"skipped"` for steps whose condition evaluated to false, and `"blocked"` for steps with unsatisfied dependencies. Resolve all static `${var}` and `${var:-default}` tokens in commands, but leave `${captured_var}` references from upstream `capture_output` declarations as-is. Exit 0 on success and 1 if the configuration is invalid.

`nexus pipeline graph <config.json>` prints a JSON object with `nodes` (an array of `{name, type}`) and `edges` (an array of `{from, to}`) representing the dependency DAG. Include `levels`, an array of arrays: `levels[0]` contains names of steps without dependencies, `levels[1]` contains steps whose dependencies are all in level 0, and so on. Exit 1 if the configuration is invalid.

## History and deletion

`nexus pipeline history <pipeline-name>` prints a JSON array of matching runs, sorted by start time descending. Each summary includes `id`, `status`, `start_time`, `end_time`, `duration_seconds` (elapsed seconds as a float), `tags` and `description`. Support `--status <status>` and `--tag <tag>` filters; the tag filter matches runs whose tags include that tag. When both filters are supplied, both must match.

`nexus pipeline delete <run-id>` removes an existing run from storage so it no longer appears in `pipeline list`, `pipeline history` or `pipeline status`. On success, print `{"deleted": "<run-id>"}` and exit 0. If the ID does not exist, print an error to stderr and exit 1.
