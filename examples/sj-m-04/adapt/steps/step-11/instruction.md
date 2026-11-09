Please expose the structured log export on the user-facing `qute://log` page via a new opt-in query parameter such as `qute://log?json`. When that parameter is present, the page should return the machine-readable JSON-Lines version of the cached log output instead of the normal human-facing view, with a suitable content type for structured data. Requests that do not opt into JSON must keep the current behavior unchanged, including the existing HTML/plaintext responses and the current `level`, `logfilter`, and `plain` query-parameter behavior.

Use the `json` query option; a case-insensitive explicit `json=false` keeps the existing HTML view.

Preserve invalid `logfilter` errors, normal URL dispatch, and the existing disabled-RAM-log notice as well as the current page layout and escaping.
