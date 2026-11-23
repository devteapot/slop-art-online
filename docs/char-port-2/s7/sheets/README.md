# char-port-2 · S7 · The sheets

**What:** the four-body proof's sheets, port against main.
- **The port arm:** every S7 port flag, on S7's final types, overlays and hair set (`swept_braid` at t2 0.65, on its own page).
- **The main arm:** the render set 61421f56f964, main's shipped assets.
- **How it's drawn:** each body is its composed line, as the game draws people. 11:00, soft film, springs off, 1600×900.
- **The client:** the dev-box's S7 client (main with hair-mirror and view-ortho).
- **The poses:** idle 2.0 s is how a person stands in the game. Bind is the measuring pose and is shown as well.

**State:** these are on S7's branch, before any rebase. The §6 cost runs and the bundle come next.

| Sheet | What to look at |
|---|---|
| [bodies-idle.png](bodies-idle.png) | The woman, man, elder and girl, port against main: front, three-quarter, back, Near and Middle (crops of the game's play stops, enlarged), and the close front. The port's hair is S5/S6's profile hair, so it reads darker at the back than main's. |
| [bodies-bind.png](bodies-bind.png) | The same bodies in bind: front, three-quarter and back. |
| [expressions-port-1.png](expressions-port-1.png), [expressions-port-2.png](expressions-port-2.png) | All 15 keys and neutral at the close-up, on the four bodies, port arm. Each key is held at full weight. These are the person files, in the bind pose, which doesn't change a face. |
| [expressions-port-main.png](expressions-port-main.png) | Blink, eye-joy and the open mouth, port against main. **Must-fix 1:** main's eye-joy shows the eye's crescent above the arc; the port's doesn't. |
| [hair-black.png](hair-black.png), [hair-brown.png](hair-brown.png), [hair-auburn.png](hair-auburn.png), [hair-grey.png](hair-grey.png) | The six styles and `swept_braid`'s cuts `.2` and `.3` on the woman, in four colours: front, three-quarter, back, Near and Middle, the plait at both. |
| [beard.png](beard.png) | The man (full beard) and the elder (short), port against main: close front, three-quarter, the side view (the GC's addition) and Middle. The port carries the beard port with the GC's option, a full beard's core near opaque. The grey under the jaw is the shaded under-jaw skin, which the beard paint doesn't cover. |
| [elders.png](elders.png) | The elders in their own looks, port against main: the elder preset, and two of Cullet's residents, Greta Dunmore (elder-f-b, 68) and Halvard Dunmore (elder-m-c, 70), from their town lines. Front, three-quarter, close and Near/Middle: **does age read at Near and Middle?** (the coordinator's question). |
| [cora.png](cora.png) | **Cora's resident line, not her hero file** (`cora-stannard`: adult-f-c, auburn, seed 37053), built from her own values, main and port. Shown in her resident hairstyle (`braid.collar`, over her coat), the coordinator's decision 2 (a). `swept_braid` is composed on her line for the record: built on her own head, the master misses its rear-depth tolerance by 0.001. |

**Notes:**
- **known: laptop's client side-asymmetry track.** Any left/right difference in the hair here is the laptop's track, not S7's.
- **The face still blinks in the view,** so a few close stills caught a blink.
- **The hair sheets** were drawn with the same t2 0.65 set before `swept_braid` moved to its own page. The files are the same; only their place on the pages differs.
- **The must-fixes' evidence** is beside the must-fixes:
  - [../eye-joy.png](../eye-joy.png) and [../final/eyes-sides.json](../final/eyes-sides.json);
  - [../t2-sweep.png](../t2-sweep.png);
  - [../cage-accept.md](../cage-accept.md);
  - [../ortho/before-after.png](../ortho/before-after.png).
- **The renders** are in `.local/char-port-2/s7/sheets2/` (bodies), `sheets/hair` and `sheets/expr`. They were composed by `.local/char-port-2/s7/compose.py`.
