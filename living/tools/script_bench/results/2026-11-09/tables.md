### Time per call under SpacetimeDB's wasmtime configuration (fuel on), µs

| engine | rates p50 | rates p99 | strike p50 | strike p99 | cooldown p50 | cooldown p99 | × native (rates) |
|---|---:|---:|---:|---:|---:|---:|---:|
| native | 0.095 | 0.098 | 0.302 | 0.309 | 0.004 | 0.004 | 1× |
| rhai | 28.5 | 30.8 | 57.7 | 70.9 | 1.48 | 1.52 | 301× |
| rhai-lean | 12.9 | 13.5 | 34.0 | 42.0 | 1.39 | 1.43 | 136× |
| rhai-map-only | 12.7 | 13.0 | 26.3 | 27.2 | 0.075 | 0.077 | 134× |
| rune | 11.7 | 12.0 | 21.8 | 25.2 | 0.269 | 0.275 | 123× |
| wasmi | 15.4 | 16.6 | 19.0 | 20.8 | 0.743 | 0.821 | 162× |
| wasmi-fuel | 16.8 | 18.4 | 20.9 | 22.9 | 0.825 | 0.886 | 177× |
| piccolo | 9.42 | 9.77 | 17.7 | 19.9 | 0.300 | 0.309 | 99× |
| koto | 12.5 | 12.8 | 22.8 | 27.1 | 0.484 | 0.499 | 132× |

### Fuel (WASM instructions) per call, and the cost of metering

| engine | rates fuel | strike fuel | cooldown fuel | rates p50 no fuel (µs) | strike p50 no fuel (µs) | metering overhead (rates) |
|---|---:|---:|---:|---:|---:|---:|
| native | 1,739 | 5,203 | 45 | 0.079 | 0.236 | +20% |
| rhai | 309,494 | 619,074 | 20,527 | 21.6 | 44.6 | +32% |
| rhai-lean | 132,677 | 358,162 | 19,557 | 10.2 | 26.9 | +27% |
| rhai-map-only | 135,729 | 279,392 | 633 | 9.00 | 18.5 | +41% |
| rune | 197,547 | 353,382 | 4,400 | 9.11 | 17.1 | +28% |
| wasmi | 82,945 | 103,160 | 4,532 | 13.4 | 17.1 | +15% |
| wasmi-fuel | 86,796 | 108,581 | 4,853 | 14.2 | 18.1 | +19% |
| piccolo | 198,161 | 361,985 | 4,306 | 8.44 | 15.9 | +12% |
| koto | 175,264 | 319,702 | 8,886 | 10.1 | 19.0 | +24% |

### Native x86_64 reference, µs (p50; same code, same fixtures)

| engine | rates | strike | cooldown | WASM/native (rates) | compile/load ms |
|---|---:|---:|---:|---:|---:|
| native | 0.037 | 0.125 | 0.002 | 2.6× | 0.00 |
| rhai | 12.1 | 22.8 | 0.550 | 2.4× | 2.76 |
| rhai-lean | 4.89 | 14.7 | 0.540 | 2.6× | 2.31 |
| rhai-map-only | 5.30 | 11.0 | 0.019 | 2.4× | 0.00 |
| rune | 5.11 | 9.49 | 0.104 | 2.3× | 3.17 |
| wasmi | 1.32 | 1.66 | 0.099 | 11.6× | 0.40 |
| wasmi-fuel | 1.42 | 1.73 | 0.100 | 11.8× | 0.40 |
| piccolo | 4.34 | 7.59 | 0.094 | 2.2× | 0.29 |
| koto | 6.07 | 12.0 | 0.256 | 2.1× | 0.35 |
| mlua | 4.54 | 8.51 | 0.045 | does not build | 0.22 |

### Load time, module size and linear memory (wasm32, fuel on)

| engine | module size | + over baseline | compile/load (ms) | compile/load fuel | memory after load | + after runs |
|---|---:|---:|---:|---:|---:|---:|
| native | 112 KiB | 0 KiB | 0.00 | 97 | 0 KiB | 0 KiB |
| rhai | 3,893 KiB | 3,781 KiB | 5.18 | 51,345,719 | 1,280 KiB | 0 KiB |
| rhai-lean | 3,893 KiB | 3,781 KiB | 5.53 | 50,219,360 | 768 KiB | 0 KiB |
| rhai-map-only | 3,893 KiB | 3,781 KiB | 0.00 | 97 | 0 KiB | 0 KiB |
| rune | 5,769 KiB | 5,657 KiB | 5.88 | 54,928,490 | 2,048 KiB | 0 KiB |
| wasmi | 2,027 KiB | 1,915 KiB | 0.61 | 3,999,535 | 1,216 KiB | 2,240 KiB |
| wasmi-fuel | 2,027 KiB | 1,915 KiB | 0.58 | 4,004,010 | 1,152 KiB | 2,240 KiB |
| piccolo | 874 KiB | 762 KiB | 0.45 | 3,114,677 | 128 KiB | 0 KiB |
| koto | 2,518 KiB | 2,406 KiB | 0.49 | 3,771,770 | 192 KiB | 0 KiB |

Baseline module (fixtures + native laws only): 112 KiB; its linear memory after fixtures: 1,600 KiB.

### Calibration: the same calls in a real SpacetimeDB 2.14.1 reducer

Energy is the reducer's `energy_quanta_used` (= wasmtime fuel); time is its host execution duration. Both are per call: (N-call reducer − empty reducer) / N, median of 5.

| engine | law | N | energy/call (host) | fuel/call (harness) | host µs/call | harness µs/call (p50) | host/harness time |
|---|---|---:|---:|---:|---:|---:|---:|
| native | rates | 20,000 | 1,739 | 1,739 | 0.092 | 0.095 | 0.97 |
| native | strike | 20,000 | 5,245 | 5,203 | 0.288 | 0.302 | 0.96 |
| native | cooldown | 400,000 | 45 | 45 | 0.004 | 0.004 | 0.99 |
| rhai | rates | 1,000 | 309,574 | 309,494 | 29.293 | 28.535 | 1.03 |
| rhai | strike | 1,000 | 617,239 | 619,074 | 56.990 | 57.712 | 0.99 |
| rhai | cooldown | 20,000 | 13,668 | 20,527 | 1.068 | 1.480 | 0.72 |
| rhai-lean | rates | 1,000 | 133,034 | 132,677 | 12.538 | 12.860 | 0.97 |
| rhai-lean | strike | 1,000 | 357,591 | 358,162 | 33.233 | 34.018 | 0.98 |
| rhai-lean | cooldown | 20,000 | 12,647 | 19,557 | 0.966 | 1.394 | 0.69 |
| rune | rates | 1,000 | 195,605 | 197,547 | 11.276 | 11.654 | 0.97 |
| rune | strike | 1,000 | 349,687 | 353,382 | 20.827 | 21.788 | 0.96 |
| rune | cooldown | 20,000 | 4,312 | 4,400 | 0.253 | 0.269 | 0.94 |
| wasmi | rates | 1,000 | 83,031 | 82,945 | 16.320 | 15.377 | 1.06 |
| wasmi | strike | 1,000 | 103,215 | 103,160 | 19.361 | 19.014 | 1.02 |
| wasmi | cooldown | 20,000 | 4,611 | 4,532 | 0.788 | 0.743 | 1.06 |
