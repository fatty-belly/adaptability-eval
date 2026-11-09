Please make `qtutils.qobj_repr` safe to call on stale Qt objects. Right now, if it gets a `QObject` wrapper whose underlying C++ object has already been deleted, it can blow up while trying to inspect the object. I want it to return a clear, safe representation for that deleted object instead of propagating a `RuntimeError`. At the same time, keep the current behavior unchanged for `None`, for ordinary non-`QObject` Python objects, and for live `QObject` instances.

Use a readable description containing the word `deleted` for the stale-object case.
