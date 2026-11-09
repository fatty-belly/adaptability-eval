Please make qutebrowser's diagnostic output useful for debugging and safe to share by default. The repository and its existing toolchain are in `/app`.

## Object descriptions

Provide `qtutils.qobj_repr` as the common object-description helper. For `None` and non-QObject values, return the ordinary Python `repr`. For live QObjects, preserve the original repr text, use one outer pair of angle brackets, and join the repr and annotations with `, `. Append a nonempty `objectName='name'`; append `className='Class'` unless the repr already contains the usual `.<Class> object at 0x` identity. A custom `RichRepr()` therefore becomes `<RichRepr(), className='RichRepr'>`. A stale Python wrapper whose C++ object was deleted must return a readable string identifying it as deleted instead of raising `RuntimeError`.

Support `include_parent=False` as the default. An explicit `include_parent=True` appends `parent=` and a readable description of the immediate parent only; do not recursively describe grandparents. If there is no parent, the result is unchanged. The ordinary call stays byte-for-byte identical when parent context is not requested.

Use that helper in the Qt tree returned by `debug.get_all_objects` and in `objreg.dump_objects`, including when an object is deleted during inspection. Preserve tree indentation and section headings. Registry dumps remain ordered lists of strings, one `name: representation` entry per registration, with the existing ` (for commands only)` suffix where applicable. Ordinary non-Qt values retain their original representation.

## RAM log retention and export

Make the RAM log handler collapse only consecutive records with the same logger name, level and rendered message. Store one retained record for each consecutive run and expose its total occurrence count as `count`; a unique record has count 1. Records with different names, levels or messages, and identical records separated by another record, remain separate. Repetition must not evict useful earlier context by occupying multiple buffer slots.

Retain newest records when shrinking a bounded buffer, preserve history when growing it, and allow zero capacity. A capacity of `-1`, at construction or after a runtime change, means an unlimited deque with no eviction and no loss of retained records. The `:debug-log-capacity` command must accept `-1` and nonnegative integers, forward them to the handler, and reject other negative values clearly.

Text and HTML dumps append ` (message repeated N times)` to records whose count exceeds 1; count-1 output remains unchanged. Preserve level thresholds and log filtering. Add `dump_log(json=True)` as an explicit JSON-Lines mode, with one JSON object per retained record. Include `created`, `msecs`, `levelname`, `name`, `module`, `funcName`, `lineno`, `levelno`, the interpolated `message`, and `count`. Include a string `traceback` when exception information exists and omit it otherwise. Calls without JSON mode keep their existing text/HTML behavior.

Expose this export through `qute://log?json` with a JSON content type. A case-insensitive explicit `json=false` retains the HTML view. Preserve the existing `level`, `logfilter` and `plain` options, invalid-filter errors, normal dispatch behavior and the disabled-RAM-log notice. The normal on-page response keeps its existing HTML layout and escaping.

## Privacy-safe diagnostic output

Apply one shared masking policy to text, HTML and JSON log output, including the JSON message and traceback. Expose the text transformation through `log.redact_url_credentials`, preserving `None` and empty strings. Use `<redacted>` as the placeholder for secret values and keep surrounding diagnostic context readable:

- In URLs, hide only a password in userinfo, retaining the username, host, port, scheme and path.
- Mask values of URL query parameters named `password`, `passwd`, `token`, `access_token`, `api_key`, `apikey`, `secret` or `auth`. Keep the parameter names and unrelated values. Match those parameter names, not substrings in names such as `authtoken`, `passwords` or `apikey2`; do not mask an ordinary value simply because it says `password`. A query fragment or text with no URL scheme is not a sensitive URL query.
- Mask credentials following the inline HTTP authorization schemes `Bearer` and `Basic`, retaining the scheme and unrelated prose. Similar ordinary words do not trigger masking.
- In `/home/<user>/...`, `/Users/<user>/...` and Windows `C:\Users\<user>\...` paths, replace only the account-name segment with a nonempty placeholder, retaining the path structure. Other paths remain untouched.

HTML must mask the same material while preserving valid escaping, existing formatting and colors. Non-sensitive output must remain unchanged. Mask the extra Open Pages, recent-history and command-line-argument fields gathered for crash reports before displaying, printing or submitting them; keep normal entries, grouping and unrelated report sections intact. Preserve the existing choice to exclude logs and extra diagnostic context from a report.

Privacy protection is automatic for all of these existing output surfaces. A trusted local developer can deliberately request raw output by setting `QUTE_DEBUG_NO_REDACT` to a recognized truthy value (`1`, `true`, `yes` or `on`, case-insensitively) before launch. An unset or empty value, false spellings and unrecognized strings must keep protection enabled. The opt-out applies consistently to text, HTML, JSON and crash-report context; raw output is never the default. Do not change the retained logger records merely to produce a masked view.
