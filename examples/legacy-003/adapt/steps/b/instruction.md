Please change closure capture to shared bindings. Snapshot copies make counters and accumulators awkward: I need a getter and setter created together to observe each other’s updates, and an outer assignment after closure creation must be visible inside. Keep the rest of the Mini contract and build/CLI behavior from my previous request. This replaces A21’s scalar snapshots and independent sibling copies. At top level, assignment to an undeclared name (for example, `g = 1;`) creates a global binding; named functions and closures must be able to read and update that binding.

- **B21** Capture by reference in both directions, for integer, string and boolean values, including compound assignments and changes of value type. For example, `let n = 10; let get = fn() { return n; }; n = 20; print get();` must print 20. Sibling closures share the original binding, so two increments followed by their sibling getter produce 1, 2, 2.

- **B22** Keep captured locals and parameters alive after their defining function returns, including across later calls that reuse stack space. Separate calls to a factory must still get independent state.

- **B23** Preserve lexical binding identity and shadowing. A new body-local let on each loop iteration gets its own binding (capturing `let saved = i` gives 0, 1, 2). A C-style for’s let initializer is one binding for that whole loop, so capturing i directly in `for (let i = 0; i < 3; i += 1)` gives 3, 3, 3 afterwards. Variables declared before a loop are shared too; reusing a stack slot or declaring an inner variable with the same name must not merge unrelated bindings.

- **B24** Sharing must work through multiple levels of nested closures and closures returned from closures. They must continue to refer to the original outer binding.

- **B25** Keep existing array/map content sharing. Since capture now shares the variable binding as well, replacing a captured array or map with a new one must be visible to its closures; the same applies when replacing a captured closure-valued variable. No syntax change is needed.
