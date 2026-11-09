`/app` contains minicc, a Mini bytecode compiler and stack-based VM. Complete and repair the existing project to satisfy this current language contract.

Keep the build and CLI interface below; implementation details and internal names are your choice. Successful programs exit zero. Invalid programs described below must terminate with a nonzero status and a diagnostic on stderr; crashes, hangs and silently succeeding are not valid errors. Exact diagnostic text is unconstrained. Each print ends with a newline; print booleans as true/false. Work entirely in `/app`; verification rebuilds a collected copy of this project using `make`.

- **R01** Build in `/app` with `make`, producing `./minicc`. Run `./minicc program.mini` to compile and execute a source file, printing one value per `print` statement. Preserve the existing integer arithmetic, booleans, variables, assignments, if/else, while, named functions, return, recursion, arrays and comments. All original programs in `/app/tests/programs/` must match their original `.expected` outputs; those fixtures are authoritative.

- **R02** String literals must interpret `\n`, `\t`, `\\`, and `\"` as newline, tab, backslash and quote.

- **R03** Use this precedence, highest first: unary `-`/`!`; `*`/`/`/`%`; `+`/`-`; comparison `==`/`!=`/`<`/`>`/`<=`/`>=`; `&&`; `||`. Operators within these binary groups associate left to right.

- **R04** Nested function calls used as arguments must preserve every argument and intermediate return value, e.g. `add(double(3), triple(2))`.

- **R05** Support `for (init; cond; step) { body }`, with a let declaration or assignment as init, an expression as condition, and an assignment or expression as step. A let initializer is scoped to that loop; assignment to an existing variable retains its updated value afterwards. Blocks and loop bodies use lexical scoping and may shadow outer names.

- **R06** `break` exits only the innermost loop; `continue` affects only that loop. Support both in while, C-style for, for..in and for..of, including nested loops and body-local declarations. In C-style for, continue runs the step before testing the condition.

- **R07** Support variable-only compound assignments `+=`, `-=`, `*=`, `/=`, `%=` for locals and globals. They compute and store the corresponding binary operation; += concatenates when a string is involved. The other compound operators require integers and reject strings. Compound assignment to an array element is outside the supported interface. At top level, assignment to an undeclared name (for example, `g = 1;`) creates a global binding; named functions and closures must be able to read and update that binding.

- **R08** `&&` and `||` short-circuit and return operand values, not normalized booleans: falsy left && yields the left, truthy left || yields the left; otherwise evaluate and return the right. Skipped operands must have no effects, errors or calls.

- **R09** `len(x)` returns the number of elements of an array or characters in a string, including zero for empty inputs.

- **R10** Anonymous expressions `fn(params) { body }` create first-class closures. A variable holding one is callable as `name(args)`; closures may be arguments, return values, array/map elements, and nested inside closures. Named functions and nested calls remain supported.

- **R11** Arrays are reference types: aliases and captured array values share in-place mutations, including growth. Support `arr[i] = value;` for a variable indexing left side; reads and writes outside bounds are runtime errors. `push(arr, value)` appends in place and returns the new length. Index-assignment left sides based on an arbitrary expression such as `make()[0] = 9` must be rejected.

- **R12** `for (i in arr)` visits array indices 0 through len(arr)-1; `for (x of arr)` visits values in order. Each iteration creates a new loop-variable binding local to its body and unavailable after the loop; empty arrays execute no body. These are the current semantics even if older repository material suggests value iteration for in.

- **R13** When either operand of + is a string, coerce the other to its string representation and concatenate. Integers use decimal text; booleans use `true`/`false`. Integer + integer remains arithmetic, and left-to-right expression evaluation matters for mixed chains.

- **R14** When both operands are strings, `<`, `>`, `<=`, `>=` compare lexicographically byte by byte. String equality and ordinary numeric comparisons still work.

- **R15** Support hash-map literals such as `{"name": "Alice", "age": 30}` and `{}`. Literal keys must be string literals and values may be any expression. Dot access `obj.name` uses a literal identifier key; bracket access `obj[key]` evaluates and coerces the key to a string (including integer and boolean keys).

- **R16** `obj.age = 31` and `obj["score"] = 95` modify a map field, creating it if absent and preserving other fields. Updating an existing key preserves its insertion position.

- **R17** `keys(obj)` returns an array of keys in insertion order. `has(obj, key)` returns a boolean presence result. `delete(obj, key)` removes a key and returns true if present, false otherwise; absent deletion preserves the map. Reinserting a removed key appends it to the order.

- **R18** `for (k in obj)` visits a hash map’s string keys in insertion order, with the same loop scoping and break/continue rules; keys can be used to look up their values.

- **R19** Maps can contain arrays, closures and maps; nested dot/bracket reads such as `data.items[1]` and `data.inner.x` must work. A closure retrieved into a variable remains callable.

- **R20** Maps are reference types: aliases and closures share mutations, additions and deletions, even when storage grows. A map is truthy iff it contains at least one key; an empty map is falsy.

- **A21** Closures capture enclosing scalar variables by value at creation time: later outer assignments do not affect captured copies, and closure assignments do not affect the outer binding. Different closures have independent scalar copies, while each closure retains its own captured state across calls. Returned closures retain captures after the defining call returns; array/map contents still share reference storage as described above.

