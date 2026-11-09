Our browser clients use JavaScript string offsets. Migrate the existing emoji library so every exposed match span and callback position uses UTF-16 code units by default. This replaces the current Python-index positions for the existing calls; keep zero-based starts and exclusive ends. Do not add a required option or a separate wrapper API.

For a Python prefix `s[:i]`, its UTF-16 offset is `sum(2 if ord(c)>0xFFFF else 1 for c in s[:i])`. Count all original input characters, including supplementary non-emoji and characters suppressed from the token stream. BMP characters, variation selectors, ZWJs, combining marks, and individual surrogate code points count as one unit. Keep strings and token text as ordinary unchanged Python strings; do not normalize input or replace supplementary scalars with surrogate characters.

Apply the new coordinates consistently to `emoji_list` fields, `analyze` and raw `tokenize` match objects, `data_copy()`, `filter_tokens` outputs, merged `EmojiMatchZWJNonRGI` objects, and every constituent produced by `split()`. Preserve the explicit start/end arguments supplied to `EmojiMatch` constructors: they are already in the new units. Splitting a match adds the UTF-16 widths of its constituents and intervening ZWJs to its supplied start; joining uses its children's original coordinates.

For example:

```python
assert emoji.emoji_list("A😀B") == [{"match_start":1,"match_end":3,"emoji":"😀"}]
f = lambda e,d: "[{},{}]".format(d["match_start"],d["match_end"])
assert emoji.replace_emoji("A😀B", replace=f) == "A[1,3]B"
```

The old results ended at 2 and returned `"A[1,2]B"`. With `"𝄞😀❤"`, the match spans must now be `(2,4)` and `(4,5)`. For `next(emoji.analyze("a👨‍👧b")).value`, the full span becomes `(1,6)` and split children have spans `[(1,3),(4,6)]`; emoji text, metadata and `join()` stay the same. Splitting `EmojiMatch("👨‍👧",10,15,data)` gives `(10,12)` and `(13,15)`.

Callable `replace_emoji` replacements and `demojize` version handlers receive UTF-16 spans of the original Unicode emoji. Callable `emojize` version handlers receive UTF-16 spans of the original shortcode including its actual delimiters, not the Unicode replacement. For instance `emojize("😀:thumbs_up:", version=-1, handle_version=f)` must return `"😀[2,13]"`. Every callback coordinate stays relative to the unmodified original input, even if earlier replacements have different lengths. Preserve callback order and all other metadata.

Keep the full library and supplied utilities working: existing imports, signatures, return containers, field names, configuration defaults, Unicode data and qualification recognition, multilingual conversion and lazy loading, aliases, NFKC shortcode lookup, custom delimiters, variants, version thresholds, counts, distinct results, detection and ZWJ keep/remove/grouping settings. Position-independent conversion and callback outputs must retain their behavior. Recognition and grouping must work correctly with these exposed coordinate units.
