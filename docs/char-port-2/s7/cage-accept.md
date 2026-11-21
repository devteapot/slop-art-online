# char-port-2 · S7 · `cage_accept.py`'s chin and jaw failures: per type (checkpoint)

**What the check does:** it builds each type's cage head (`cage_head.CageFace`), measures it with the reference tool (`reference/measure.py`, `face_types.measure_one`), and compares the face's width within 0.15 H and 0.30 H of depth behind the bridge (`w15`, `w30`) at the heights 0.04–0.76 H with the type's record (`types.json` `sections`), to 0.03 H.

**Its known-answer test first** ([cage_accept_selftest.py](../../../living/tools/characters/cage_accept_selftest.py)):
- a synthetic head of known `w15` and `w30` at every height, with two eye holes and a nose, through `cage_accept`'s own GLB writer, the reference tool and `measure_one`;
- **18 of 18 checks pass**: every width to 0.001 H, the eye's height and the eyes' spacing.
- One property found, now written into the test: the tool takes the cut's own points, not points interpolated at a depth threshold, so a threshold falling between two vertices reads the nearer one.

**The runs** ([cage/](cage/)):

| Configuration | Within 0.03 H |
|---|---|
| no port | 1 of 21 |
| S1–S4 (`jaw,jaw_shell,paint,neck,ink`) | 3 of 21 |
| main's whole port (with `faceprop`) | 8 of 21 |

Every failure is one of two kinds.

## S1's own record of intent

From [s1/README.md](../s1/README.md), its checks table and the note under it:

> | `cage_accept.py`, flag off (main) | **Fails 20 of 21 types**, all at the chin (0.04 H, width within 0.30 H): the cage builds the chin's sides wider than the type records, by 0.03–0.07 H. This is main's state. |
>
> | `cage_accept.py`, flag on | 3 of 21 pass (adult-m-c, elder-m-c, youth-m-c). The 0.04 H excess falls on every type (e.g. adult-f-b 0.044 → 0.025 H). On women's types the front width at 0.04–0.12 H now runs under the record by up to 0.053 H. This is the taper's purpose: the records are the VRoid reference's proportions, not the drawing's. |
>
> Plan §7 named `cage_accept.py` as S1's acceptance, but it fails on main. It is a measure here, not a gate. If the tapered lower face is accepted, the type records' 0.04 H and 0.12 H widths should follow it.

And from S1's "What the tapers are" ([s1/README.md](../s1/README.md)): "Each is a fractional offset of the local half-width. The chin's applies below 0.095 H; the jaw's from 0.15 to 0.27 H."

## A: the jaw's side at the chin's height (`w30` at 0.04 H, built wider): a defect, to fix

**What it is:**
- On the reference (Shino), the cut at 0.04 H ends 0.22 H behind the bridge, and nothing in it is wider beyond 0.15 H than within it (`w15` = `w30` = 0.187): just behind the chin her jaw's underside has risen above the chin's height.
- On the cage, the widest point of that cut within 0.30 H lies 0.18–0.23 H back, on the jaw's side (above the cage's jaw line on lines a and b): the jaw line still runs at the chin's height there. The cage's jaw rises too slowly behind the chin.
- It is main's (no port: +0.029 to +0.069 H on every type); S1's chin taper narrows it in part.
- It is the remainder char-4-faces' merge named ("known remainder the man's rear jaw rise (0.186H, Shino 0.229H)").
- On the long lines (c) part of it is coverage: the cage's skin carries on under its jaw line, where the reference's face mesh stops. Leaving out the cage's skin below its jaw line takes 0.016–0.035 H off the c lines, and nothing off a and b (column "jaw-line cut").

**The fix (proposed):** the jaw line rising sooner behind the chin, in `cage_head`'s jaw line (`Plan.jaw_line`, `jaw_z`), behind the port's `jaw` feature (S1's), so main is unchanged.
- **Acceptance:** `w30` at 0.04 H within 0.03 H of the record on all 21 types.
- **Shown:** the profile and the three-quarter, before and after; the 2D face measure unchanged (its cheek row is far above); the jaw lines' order; `face_types check`; the crossings.
- The coverage on the c lines is decided after the fix: if their excess remains only below the jaw line, `cage_accept` measures the skin above the jaw line, as the reference's face mesh is.

## B: the front's width at 0.04–0.12 H (built narrower): S1's tapers, on purpose; re-baseline

**What it is:** on the women's classes (the tapers −0.145 to −0.18 at the chin, −0.02 to −0.05 at the jaw), `w15` at 0.04 and 0.12 H and `w30` at 0.12 H run under the record by up to 0.053 H. S1: "This is the taper's purpose".

**The re-baseline:** `cage_accept` compares those widths with the record **times the taper the cage itself applies** at that height (`1 + chin_taper × chin weight + jaw_taper × jaw weight`, S1's weights). It is not a change to `types.json`: the records are what the cage is built from, and the taper would then act twice. Against the tapered records the front cells are within 0.032 H (they were 0.053). The one cell at 0.032, adult-f-c's `w30` at 0.12 H, has its widest point partly on the jaw's side, outside the tapered rows; it is decided with A's fix.

## Per type

- **A, `w30` at 0.04 H, built − record:** no port / S1–S4 / main's whole port / main's port with the skin cut at the jaw line. "within (taper)" means over 0.03 H on main without the port, within it once S1's chin taper narrows it.
- **B, `w15` at 0.04, `w15` at 0.12, `w30` at 0.12 H, main's whole port:** against the record → against the tapered record.

| Type | Tapers (chin / jaw) | A: `w30` at 0.04 H | A | B: against the record | B: against the tapered record | B |
|---|---|---|---|---|---|---|
| adult-f-a | -0.180 / -0.050 | +0.047 / +0.007 / +0.007 / +0.007 | within (taper) | -0.036 / -0.053 / -0.053 | +0.006 / -0.003 / +0.001 | **S1 departure** |
| adult-f-b | -0.180 / -0.050 | +0.044 / +0.025 / +0.025 / +0.013 | within (taper) | -0.026 / -0.040 / -0.030 | +0.006 / +0.000 / +0.015 | **S1 departure** |
| adult-f-c | -0.180 / -0.050 | +0.069 / +0.058 / +0.058 / +0.023 | **defect** | -0.017 / -0.031 / -0.006 | +0.005 / +0.002 / +0.032 | **S1 departure** |
| adult-m-a | -0.060 / +0.000 | +0.054 / +0.036 / +0.028 / +0.028 | within (taper) | -0.010 / -0.017 / -0.012 | +0.007 / -0.004 / +0.002 | within |
| adult-m-b | -0.060 / +0.000 | +0.043 / +0.035 / +0.024 / +0.020 | within (taper) | -0.008 / -0.010 / -0.005 | +0.006 / +0.000 / +0.006 | within |
| adult-m-c | -0.060 / +0.000 | +0.033 / +0.026 / +0.017 / +0.001 | within (taper) | -0.011 / -0.002 / +0.007 | +0.003 / +0.007 / +0.017 | within |
| child-u-a | -0.100 / +0.000 | +0.056 / +0.035 / +0.032 / +0.032 | **defect** | -0.025 / -0.028 / -0.024 | +0.001 / -0.005 / +0.001 | within |
| child-u-b | -0.100 / +0.000 | +0.048 / +0.031 / +0.029 / +0.029 | within (taper) | -0.018 / -0.020 / -0.009 | +0.003 / -0.001 / +0.012 | within |
| child-u-c | -0.100 / +0.000 | +0.043 / +0.035 / +0.032 / +0.025 | **defect** | -0.012 / -0.014 / +0.003 | +0.005 / +0.002 / +0.021 | within |
| elder-f-a | -0.160 / -0.020 | +0.044 / +0.009 / +0.005 / +0.005 | within (taper) | -0.035 / -0.041 / -0.042 | +0.005 / -0.003 / -0.001 | **S1 departure** |
| elder-f-b | -0.160 / -0.020 | +0.042 / +0.016 / +0.011 / +0.011 | within (taper) | -0.027 / -0.031 / -0.021 | +0.004 / -0.000 / +0.014 | **S1 departure** |
| elder-f-c | -0.160 / -0.020 | +0.061 / +0.050 / +0.045 / +0.021 | **defect** | -0.020 / -0.024 / -0.002 | +0.003 / +0.001 / +0.027 | within |
| elder-m-a | -0.050 / +0.000 | +0.058 / +0.041 / +0.036 / +0.036 | **defect** | -0.007 / -0.015 / -0.012 | +0.008 / -0.004 / -0.000 | within |
| elder-m-b | -0.050 / +0.000 | +0.045 / +0.034 / +0.027 / +0.027 | within (taper) | -0.005 / -0.010 / -0.007 | +0.007 / -0.001 / +0.003 | within |
| elder-m-c | -0.050 / +0.000 | +0.030 / +0.024 / +0.018 / +0.006 | within (taper) | -0.008 / -0.003 / +0.004 | +0.004 / +0.005 / +0.012 | within |
| youth-f-a | -0.145 / -0.040 | +0.048 / +0.015 / +0.015 / +0.015 | within (taper) | -0.029 / -0.042 / -0.047 | +0.005 / -0.003 / -0.004 | **S1 departure** |
| youth-f-b | -0.145 / -0.040 | +0.044 / +0.026 / +0.026 / +0.018 | within (taper) | -0.020 / -0.031 / -0.025 | +0.006 / +0.001 / +0.011 | **S1 departure** |
| youth-f-c | -0.145 / -0.040 | +0.068 / +0.059 / +0.059 / +0.027 | **defect** | -0.014 / -0.024 / -0.004 | +0.004 / +0.002 / +0.026 | within |
| youth-m-a | -0.050 / +0.000 | +0.058 / +0.042 / +0.036 / +0.036 | **defect** | -0.008 / -0.012 / -0.012 | +0.006 / -0.001 / -0.001 | within |
| youth-m-b | -0.050 / +0.000 | +0.046 / +0.033 / +0.028 / +0.028 | within (taper) | -0.006 / -0.009 / -0.006 | +0.006 / +0.000 / +0.004 | within |
| youth-m-c | -0.050 / +0.000 | +0.029 / +0.024 / +0.017 / +0.007 | within | -0.008 / -0.004 / +0.005 | +0.004 / +0.004 / +0.014 | within |

- **Defects to fix (A, over 0.03 H with main's port):** adult-f-c, child-u-a, child-u-c, elder-f-c, elder-m-a, youth-f-c, youth-m-a. The fix aims at A on every type, since the "within (taper)" ones carry the same excess at +0.017 to +0.029 H.
- **S1 departures to re-baseline (B):** adult-f-a, adult-f-b, adult-f-c, elder-f-a, elder-f-b, youth-f-a, youth-f-b.
- **No eye or nose failures:** the eye's height and spacing are within 0.02 H on every type.
