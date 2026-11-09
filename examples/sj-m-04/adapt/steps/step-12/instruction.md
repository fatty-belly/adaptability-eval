Please make diagnostic logs safe to share when they contain URLs with inline credentials. If a log entry includes a URL where the password is embedded in the userinfo portion before the host, the password must be masked in the log output a user sees or copies, while leaving the rest of the URL readable. Log output that does not contain this kind of URL password should remain exactly unchanged.

Expose the shared string transformation as `log.redact_url_credentials`. Use `<redacted>` for masked secret values and preserve None and empty input.
