# Dungeon lighting themes

The lighting engine is too good to leave the dungeon on torches on repeat. Want to start hammering?

Add a rules-owned `LightEmitter` component so room generation can place lighting intent as data. One entity carries one flat light: `radius`, `color` (RGB array), `pattern`, `softness`, and `voidStrength` (default null). Null means normal light; a non-null strength, including zero, means void/absorptive light. Use the existing temporal pattern vocabulary. Project positioned emitters through `buildWorldView` as `view.lightEmitters`, then consume them generically in `collectLightSources`. Center sources on their grid tile, preserve negative coordinates, and let authored lighting win over same-entity identity lighting without a duplicate bloom. Emitters with nonpositive radius do not light anything; memory echoes must not illuminate.

For this first pass, wire the existing features into their room themes:

- Crypt sarcophagi and urns: small, soft, warm candle/ember pools.
- Hydraulic steam vents and pressure plinths: cold blue-green pulses.
- Mushrooms in spider spaces: dim green-blue bioluminescence.
- Shrines and altars: holy light; allow a shrine's spawn params to override its emitter with `lightEmitter`, including void/occult lighting for a dark shrine.
- Weapon racks: tight, sharp metal highlights.
- Cooking fires: warm fire and ember light.

Keep the existing generation/materialization paths and reactive, carried, event and status lighting working. Keep rules/display imports separated. Floor and volume effects can wait.

Development environment: Deno 2.4.4 is installed. The pinned standard library is vendored under `/opt/deps`; run repository tests with `deno test --config=/opt/deps/deno.json --allow-read --no-check tests/`.
