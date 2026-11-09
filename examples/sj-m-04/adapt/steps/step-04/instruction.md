Please improve the recursive Qt object dump returned by `debug.get_all_objects`. Right now the Qt object-tree output is too bare and can be fragile because it shows plain Python `repr()` values for child objects. I want each listed Qt object in that dump to use the richer QObject-style representation, so the output includes useful `objectName`/class information when available, and the dump stays safe to generate even if one of the Qt objects gets deleted while the tree is being walked.

Preserve the existing tree indentation and section headings while replacing the object descriptions.
