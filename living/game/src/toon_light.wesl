// The shared toon look (docs/GAME_BRIEF.md, "Art direction"), imported as
// `living_game::toon_light`: the toon parameters every material binds (style.rs `ToonParams`), the
// wind sway of plants, and the lighting pieces that toon.wesl (every model) and terrain.wesl (the
// ground) compose, so the ground and the scenery are lit by one model:
// - the sun in two bands with a soft, brush-broken edge and a darker core where surfaces turn
//   away;
// - shadows made by moving the lit colour's hue toward the scene's (`shadow_of`), saturation kept;
// - the sky's fill, which lifts shadows and keeps nights readable, and glow that shines more at
//   night (both from the ambient light that daylight.rs sets);
// - rain darkening and puddles, a rim light, and banded point lights.
// Anything unused by a shader is stripped from it, so vertex and prepass shaders may import only
// `toon` and `sway`.

import bevy_pbr::render::{
    mesh_view_bindings as view_bindings,
    shadows,
    mesh_view_types,
    clustered_forward,
};

struct Toon {
    // rgb: shadow tint (multiplies lit colour in shadow), a: how dark shadows get (0..1).
    shadow: vec4<f32>,
    // rgb: rim colour, a: rim strength.
    rim: vec4<f32>,
    // x: band threshold (N·L), y: band softness, z: brush breakup, w: rim width (power).
    band: vec4<f32>,
    // x: brush scale (1/m), y: ambient lift, z: second (core) band darkness, w: exposure.
    extra: vec4<f32>,
    // Shadow colour by hue shift (Blue Protocol): x target hue (0..1), y how far toward it,
    // z saturation multiplier, w: the material's kind (style.rs `Kind`).
    shade: vec4<f32>,
    // Recolouring (characters.rs): x the target hue, y saturation and z value factors (>= 0
    // scales toward 0; < 0 scales the distance to 1 by -f), w mode: 0 none, 1 shift, 2 tint,
    // 3 per instance (the target colour is in the mesh's tag; see toon.wesl `recolor`).
    recolor: vec4<f32>,
    // x: the texture's mean hue, y: how much of its hue variation stays (mode 1); in mode 3,
    // z and w: the texture's mean saturation and value.
    recolor_from: vec4<f32>,
    // Weather (weather.rs): x wind strength (the vertex shaders sway plants), y wetness;
    // z: painted detail strength on models (0 off), w: how far detail's relief moves the band.
    atmo: vec4<f32>,
    // Faces: x shadow-edge softness, y face shadow depth (times skin's), z how far eyes and
    // mouth darken in shadow, w face rim.
    face: vec4<f32>,
    // Hair: x angel-ring strength, y ring width, z ring position (tangent shift), w rim.
    hair: vec4<f32>,
    // Hair's ring, its shape: x edge softness (0 hard, 1 fading from the middle), y comb teeth
    // (0 none, 1 full), z break-up by the strand picture (0 none, 1 full), w the teeth's scale
    // across the strands (uv.x times it).
    hair_sheen: vec4<f32>,
    // Where on the head the ring may lie: x how far up a surface must face (N·up where it starts,
    // full 0.25 above), y from how far it faces the character's forward it fades (2 never); z how
    // many bins of a lock's `_GREY` make one lock (toon.wesl `hair_light`); w the view-placed
    // ring's width on hair without char-4's lock data, when the ring is placed at a height.
    hair_place: vec4<f32>,
    // The ring by height and lock: x the share of locks without it, y how far it moves up or down
    // a lock (in N·up), z 0 placed by the view, 1 at a height (where N·up is w).
    hair_lock: vec4<f32>,
    // Painted detail (toon.wesl `detail`): x 1 where the vertex colours' alpha names surfaces
    // (generated scenery), z full detail until (m), w none from (m).
    detail: vec4<f32>,
    // A hand-made hair profile (style.rs `Kind::HandHair`, handmade.rs): shade, mid, light and
    // highlight as linear rgb; hand[3].w 1 when the highlight mask is a texture (`face_map`),
    // hand[0].w 1 when its B is the strands (v1.3.1 `strands`).
    hand: array<vec4<f32>, 4>,
    // The profile's x t1, y t2 (N·L), z edge, w highlight feather.
    hand_bands: vec4<f32>,
    // A hand-made file's forward in the mesh's own frame (xyz), w 1 when set (toon.wesl `facing`).
    file: vec4<f32>,
    // A profile's lock ink (v1.1): rgb linear colour, w ink_px.
    hand_ink: vec4<f32>,
    // x ink_range (UV), y ink_fade_px, z 1 when ink is drawn.
    hand_ink_range: vec4<f32>,
    // A material's general ink (contract v1.2, toon.wesl `ink_map`): rgb linear colour, w px
    // (width "px") or min_px (width "uv").
    ink: vec4<f32>,
    // x range (UV), y fade_px, z mode (0 none, 1 "px", 2 "px" with taper, 3 "uv", 4 "uv" through the derivatives: PERF inkfw), w metres
    // per UV unit (0 unknown).
    ink_shape: vec4<f32>,
    // A palette material (contract v1.3, characters/palette.rs): x 1 when a hair profile's
    // swatches and ink come from the mesh's palette entry (hair_tints, tag bit 27), y 1 when the
    // general ink's colour does (row 4).
    palette: vec4<f32>,
    // Per surface (style.rs `Surface`): x 1 / tile size (1/m), y strength, z mapping (0
    // triplanar, 1 planar per face).
    layers: array<vec4<f32>, 18>,
    // A seated character's skirted piece (characters.rs `seat_clamp`, hem-ground): xyz the seat
    // plane's upward normal, w its offset a margin up; zero on every shared material.
    seat: vec4<f32>,
    // The look-dev light (style.rs `Look`, `ld_*` below): x 1 on, y the character rim's strength,
    // z the specular's strength, w the share of the classic rim scenery keeps. All zero in the
    // classic look, whose code paths are untouched.
    look: vec4<f32>,
    // x the sky's fill (times the sun's brightness), y the ground's warm bounce (times the sun),
    // z cloth and scenery shadow depth, w skin shadows' saturation.
    look_light: vec4<f32>,
    // x 1 on a character's material.
    character: vec4<f32>,
    // The look-dev ramp on characters: x the band threshold (N·L), y the brush breakup's share;
    // z how much of the sun's colour shadows keep (0 none: their colour is the sky's).
    look_ramp: vec4<f32>,
}

@group(constants::MATERIAL_BIND_GROUP) @binding(100)
var<uniform> toon: Toon;

// What the material shades (style.rs `Kind`, in `shade.w`).
fn is_kind(k: f32) -> bool {
    return abs(toon.shade.w - k) < 0.5;
}

// Plants lean with the wind. The mesh tag says whether a mesh sways (bit 25) and how (bits 26-27:
// 0 grass and flowers, 1 bushes, 2 trees); weather.rs sets it. Sway grows with height above the
// instance's origin, so trunks stay planted and crowns move; each instance has its own phase.
// toon_vertex.wesl and toon_prepass.wesl both use it, so every pass moves plants alike.
fn sway(world: vec3<f32>, origin: vec3<f32>, tag: u32, t: f32) -> vec3<f32> {
    let wind = toon.atmo.x;
    if ((tag & (1u << 25u)) == 0u || wind <= 0.0) {
        return world;
    }
    let kind = (tag >> 26u) & 3u;
    let h = max(world.y - origin.y, 0.0);
    var amp = h * h * 0.0016;
    if (kind == 0u) {
        amp = h * 0.16;
    } else if (kind == 1u) {
        amp = h * h * 0.02;
    }
    let phase = origin.x * 0.21 + origin.z * 0.17;
    // A slow gust that travels across the land, a sway, and a quick flutter near the tips.
    let gust = 0.55 + 0.45 * sin(t * 0.45 - origin.x * 0.035 - origin.z * 0.02);
    let swing = sin(t * 1.6 + phase) * 0.7 + sin(t * 2.9 + phase * 1.7) * 0.3;
    let flutter = sin(t * 7.0 + world.x * 1.3 + world.z * 1.1) * 0.12 * min(h, 3.0) / 3.0;
    let dir = vec2<f32>(0.94, 0.34);
    let side = vec2<f32>(-dir.y, dir.x);
    let lean = amp * wind * (gust * 0.8 + swing * (0.35 + 0.25 * wind));
    let off = dir * lean + side * amp * wind * (flutter + swing * 0.25);
    return world + vec3<f32>(off.x, -abs(lean) * 0.15, off.y);
}

// A seated character's skirted cloth stays on the ground's side of its seat (hem-ground): every
// vertex below the plane in `toon.seat` (a margin above the weighted ground, characters.rs
// `seat_clamp`) is moved onto it along its normal, so a coat's panel pressed under a thigh lies
// flat on the ground. Materials without a seat (all shared ones) are untouched. toon_vertex.wesl
// and toon_prepass.wesl both apply it, so the lines, depth and shadows agree.
fn seat_clamp(world: vec3<f32>) -> vec3<f32> {
    let n = toon.seat.xyz;
    if (dot(n, n) < 0.25) {
        return world;
    }
    let h = dot(n, world) - toon.seat.w;
    return select(world, world - n * h, h < 0.0);
}

fn hash3(p: vec3<f32>) -> f32 {
    let q = fract(p * 0.1031);
    let r = q + dot(q, q.yzx + 33.33);
    return fract((r.x + r.y) * r.z);
}

// Value noise, for breaking up band edges like brush strokes.
fn noise3(p: vec3<f32>) -> f32 {
    let i = floor(p);
    let f = fract(p);
    let u = f * f * (3.0 - 2.0 * f);
    let n000 = hash3(i);
    let n100 = hash3(i + vec3(1.0, 0.0, 0.0));
    let n010 = hash3(i + vec3(0.0, 1.0, 0.0));
    let n110 = hash3(i + vec3(1.0, 1.0, 0.0));
    let n001 = hash3(i + vec3(0.0, 0.0, 1.0));
    let n101 = hash3(i + vec3(1.0, 0.0, 1.0));
    let n011 = hash3(i + vec3(0.0, 1.0, 1.0));
    let n111 = hash3(i + vec3(1.0, 1.0, 1.0));
    let x00 = mix(n000, n100, u.x);
    let x10 = mix(n010, n110, u.x);
    let x01 = mix(n001, n101, u.x);
    let x11 = mix(n011, n111, u.x);
    return mix(mix(x00, x10, u.y), mix(x01, x11, u.y), u.z);
}

fn rgb_to_hsv(c: vec3<f32>) -> vec3<f32> {
    let mx = max(c.r, max(c.g, c.b));
    let mn = min(c.r, min(c.g, c.b));
    let d = mx - mn;
    var h = 0.0;
    if (d > 1e-5) {
        if (mx == c.r) {
            h = (c.g - c.b) / d + select(0.0, 6.0, c.g < c.b);
        } else if (mx == c.g) {
            h = (c.b - c.r) / d + 2.0;
        } else {
            h = (c.r - c.g) / d + 4.0;
        }
        h = h / 6.0;
    }
    return vec3(h, select(0.0, d / mx, mx > 1e-5), mx);
}

fn hsv_to_rgb(c: vec3<f32>) -> vec3<f32> {
    let k = vec3(1.0, 2.0 / 3.0, 1.0 / 3.0);
    let p = abs(fract(vec3(c.x) + k) * 6.0 - 3.0);
    return c.z * mix(vec3(1.0), clamp(p - 1.0, vec3(0.0), vec3(1.0)), c.y);
}

// A shadow colour from a lit colour: the hue moved toward a target, saturation kept (or
// raised), brightness lowered.
fn shadow_of(lit: vec3<f32>, value: f32, scene_hue: f32) -> vec3<f32> {
    var hsv = rgb_to_hsv(lit);
    // Skin keeps a warm shadow (toward red-orange) instead of the scene's cool target, so faces
    // never turn purple or flushed. Coloured hair darkens in its own hue, richer, as anime hair
    // does; near-grey hair (white, black) has no hue of its own and keeps the scene's tint,
    // which gives it depth.
    let skin = is_kind(1.0) || is_kind(2.0);
    let hair = is_kind(4.0);
    let own = select(0.0, smoothstep(0.12, 0.35, hsv.y), hair);
    let target_hue = select(scene_hue, 0.015, skin);
    // Reds and oranges reach a violet target through magenta, which reads as pink roofs and
    // cloth; they take a quarter of the shift and simply deepen instead.
    let red = 1.0 - smoothstep(0.05, 0.12, abs(hsv.x - round(hsv.x)));
    let shift = select(toon.shade.y * (1.0 - 0.75 * red), 0.35, skin) * (1.0 - own);
    var d = target_hue - hsv.x;
    d = d - round(d);
    hsv.x = fract(hsv.x + d * shift);
    hsv.y = clamp(hsv.y * mix(toon.shade.z, max(toon.shade.z, 1.12), own), 0.0, 1.0);
    hsv.z = hsv.z * value;
    return hsv_to_rgb(hsv);
}

// The time of day and the region (daylight.rs) arrive through the scene's ambient light: its
// colour is the sky's fill (it lifts shadows and dark scenes, and its hue is the shadows' target
// hue), its alpha how strongly glowing things shine (0: no atmosphere; the material's own
// shadow hue applies and nothing is lifted).
struct Scene {
    fill: vec3<f32>,
    hue: f32,
    glow: f32,
}

fn scene() -> Scene {
    let amb = view_bindings::lights.ambient_color;
    let atmo = amb.a > 0.0;
    let fill = select(vec3<f32>(0.0), amb.rgb, atmo);
    let fill_hsv = rgb_to_hsv(fill);
    return Scene(fill, select(toon.shade.x, fill_hsv.x, atmo && fill_hsv.y > 0.02), select(1.0, amb.a, atmo));
}

// Rain darkens surfaces, upward ones most.
fn wetted(albedo: vec3<f32>, N: vec3<f32>) -> vec3<f32> {
    return albedo * (1.0 - toon.atmo.y * (0.16 + 0.14 * clamp(N.y, 0.0, 1.0)));
}

// View-space depth, for shadow cascades and light clusters.
fn view_depth(p: vec4<f32>) -> f32 {
    return dot(vec4<f32>(
        view_bindings::view.view_from_world[0].z,
        view_bindings::view.view_from_world[1].z,
        view_bindings::view.view_from_world[2].z,
        view_bindings::view.view_from_world[3].z
    ), p);
}

// The sun's shadow at `at` (1 lit), where the sun casts one.
fn sun_shadow(at: vec4<f32>, world_normal: vec3<f32>, view_z: f32, frag: vec2<f32>) -> f32 {
    let light = &view_bindings::lights.directional_lights[0];
    if (((*light).flags & mesh_view_types::DIRECTIONAL_LIGHT_FLAGS_SHADOWS_ENABLED_BIT) != 0u) {
        return shadows::fetch_directional_shadow(0u, at, world_normal, view_z, frag);
    }
    return 1.0;
}

// The sunlit level of a white surface: Lambert's 1/π, at the camera's exposure.
fn sun_color() -> vec3<f32> {
    return view_bindings::lights.directional_lights[0].color.rgb * view_bindings::view.exposure / 3.14159265 * toon.extra.w;
}

// The sun's bands at N·L: x the lit band (its edge wandering like a brush stroke), y the core,
// 0 where the surface turns fully away.
fn bands(ndl: f32, p: vec3<f32>) -> vec2<f32> {
    let brush = (noise3(p * toon.extra.x) - 0.5) * toon.band.z;
    let t = toon.band.x + brush;
    return vec2<f32>(
        smoothstep(t - toon.band.y, t + toon.band.y, ndl),
        smoothstep(-0.35 + brush, -0.15 + brush, ndl)
    );
}

// The surface's colour, lit `lit` (0..1) by `sun`, in shadow its hue-shifted colour at `value`,
// plus the sky's fill (strongest in shadow).
fn banded(albedo: vec3<f32>, sun: vec3<f32>, lit: f32, value: f32, sc: Scene) -> vec3<f32> {
    let lit_color = albedo * sun;
    let shadow_color = shadow_of(lit_color, value, sc.hue) * toon.shadow.rgb + albedo * sun * toon.extra.y;
    let color = mix(shadow_color, lit_color, lit);
    return color + albedo * sc.fill * mix(1.0, 0.45, lit);
}

// Puddles: on wet flat ground, small dark patches that mirror the fog's sky colour, more of it
// the flatter they are seen (a puddle across the street shines, one at your feet shows the
// ground through it), with a light rim. `low` (> 0) gathers them in hollows.
fn puddles(color: vec3<f32>, p: vec3<f32>, low: f32) -> vec3<f32> {
    var c = color;
    let wet = toon.atmo.y;
    let n = noise3(vec3<f32>(p.x * 0.55, 0.0, p.z * 0.55)) * 0.65 + noise3(vec3<f32>(p.x * 1.7, 3.0, p.z * 1.7)) * 0.35 + low;
    let th = 0.77 - 0.05 * wet;
    let puddle = smoothstep(th, th + 0.06, n) * smoothstep(0.05, 0.6, wet);
    let rim = (smoothstep(th - 0.01, th + 0.01, n) - smoothstep(th + 0.02, th + 0.045, n)) * smoothstep(0.05, 0.6, wet);
@if(DISTANCE_FOG) {
    let sky = view_bindings::fog.base_color.rgb;
    let up = clamp(normalize(eye() - p).y, 0.0, 1.0);
    let grazing = pow(1.0 - up, 3.0);
    c = mix(c, c * 0.48 + sky * (0.06 + 0.3 * grazing), puddle);
    c = c + sky * rim * 0.12;
}
    return c;
}

// A wet surface's sheen: the sky's colour caught at grazing angles on what faces up (rain;
// `toon.atmo.y`), so a soaked street brightens toward the distance while near ground darkens.
fn wet_sheen(color: vec3<f32>, N: vec3<f32>, V: vec3<f32>) -> vec3<f32> {
    var c = color;
@if(DISTANCE_FOG) {
    let wet = smoothstep(0.05, 0.8, toon.atmo.y);
    let up = smoothstep(0.35, 0.95, N.y);
    let fr = pow(clamp(1.0 - max(dot(N, V), 0.0), 0.0, 1.0), 4.0);
    c = c + view_bindings::fog.base_color.rgb * fr * up * wet * 0.45;
}
    return c;
}

fn fresnel(N: vec3<f32>, V: vec3<f32>) -> f32 {
    return clamp(1.0 - max(dot(N, V), 0.0), 0.0, 1.0);
}

// Rim light on silhouettes, stronger on the lit side (times the sun).
fn rim_light(fr: f32, lit: f32, strength: f32) -> vec3<f32> {
    return toon.rim.rgb * pow(fr, toon.band.w) * strength * (0.35 + 0.65 * lit);
}

// Local lights (point lights: lamps, crystals, neon), banded like the sun, no shadows.
fn point_lights(albedo: vec3<f32>, p: vec3<f32>, N: vec3<f32>, view_z: f32, frag: vec2<f32>, ortho: bool) -> vec3<f32> {
    var color = vec3<f32>(0.0);
    let cluster = clustered_forward::view_fragment_cluster_index(frag, view_z, ortho);
    let ranges = clustered_forward::unpack_clusterable_object_index_ranges(cluster);
    for (var i: u32 = ranges.first_point_light_index_offset; i < ranges.first_spot_light_index_offset; i = i + 1u) {
        let id = clustered_forward::get_clusterable_object_id(i);
        let l = &view_bindings::clustered_lights.data[id];
        let to = (*l).position_radius.xyz - p;
        let d2 = dot(to, to);
        let f = d2 * (*l).color_inverse_square_range.w;
        let window = clamp(1.0 - f * f, 0.0, 1.0);
        let fall = window * window / max(d2, 0.0001);
        let b = smoothstep(-0.05, 0.12, dot(N, normalize(to))) * 0.8 + 0.2;
        color = color + albedo * (*l).color_inverse_square_range.rgb * fall * b * view_bindings::view.exposure / 3.14159265 * toon.extra.w;
    }
    return color;
}

// Emission (fires, lamps); it reads stronger at night.
fn emission(e: vec3<f32>, sc: Scene) -> vec3<f32> {
    return e * view_bindings::view.exposure * sc.glow;
}

// Whether the scene has a sun.
fn has_sun() -> bool {
    return view_bindings::lights.n_directional_lights > 0u;
}

fn sun_direction() -> vec3<f32> {
    return view_bindings::lights.directional_lights[0].direction_to_light;
}

// The camera's position.
// The metres a screen pixel spans at view depth `z` (`view_depth`), in a perspective view: smooth
// across the screen, unlike screen derivatives, which step between 2x2 pixel quads.
fn metres_per_pixel(z: f32) -> f32 {
    let k = view_bindings::view.clip_from_view[1][1];
    return abs(z) * 2.0 / max(k * view_bindings::view.viewport.w, 1e-4);
}

fn eye() -> vec3<f32> {
    return view_bindings::view.world_position.xyz;
}

// The look-dev light (style.rs `Look::Lookdev`, look-dev step 1). Only pipelines with the shader
// def LOOKDEV (style.rs `ToonKey`, terrain.rs) call these; the classic look's code is as before.

// The sun's bands with the look-dev light: characters' own ramp (`ld_bands`), everything else
// as before.
fn ld_band_pair(ndl: f32, relief: f32, p: vec3<f32>) -> vec2<f32> {
    if (toon.character.x > 0.5) {
        return ld_bands(ndl, p);
    }
    return bands(ndl + relief, p);
}

// How warm the key light is (0 for cool moonlight or neutral white, 1 for warm daytime/dusk sun):
// gates sun-desaturation, skin's warm shadow shift, and warm ground bounce so cool moonlight stays
// cool in shadow instead of turning skin orange-tan or ground green.
fn ld_sun_warmth(sun: vec3<f32>) -> f32 {
    return smoothstep(0.02, 0.25, (sun.r - sun.b) / max(luma(sun), 1e-4));
}

// The shadow's value with the look-dev light: cloth and scenery at look_light.z (softened slightly
// under cool night moonlight so outer-plaza figures stay legible); skin deepened modestly by day
// for clearer form turn; face parts as before.
fn ld_value(depth: f32, away: f32, skin: bool, part: bool, warm: f32) -> f32 {
    if (part) {
        return 1.0 - depth;
    }
    if (skin) {
        let scale = select(1.26, 1.12, is_kind(2.0));
        return 1.0 - depth * mix(1.0, scale, warm);
    }
    let d = toon.look_light.z - 0.08 * (1.0 - warm);
    return (1.0 - d) * away;
}

fn luma(c: vec3<f32>) -> f32 {
    return dot(c, vec3<f32>(0.2126, 0.7152, 0.0722));
}

// The light that isn't the sun, by the surface's facing: the sky's fill from above, in the
// scene's shadow hue (cool by day, violet at dusk, blue at night) at a share of the sun's
// brightness, and the sunlit ground's warm bounce from below (gated on sun warmth so moonlight
// stays cool under chins). Skin takes less of the extra sky tint by day/dusk so dusk jaws stay
// warm peach rather than mauve.
fn ld_hemi(N: vec3<f32>, sun: vec3<f32>, sc: Scene, warm: f32, skin: bool) -> vec3<f32> {
    let sky_tint = hsv_to_rgb(vec3<f32>(sc.hue, 0.55, 1.0)) * luma(sun) * toon.look_light.x;
    let sky_scale = select(1.0, mix(1.0, 0.45, warm), skin);
    let sky = sky_tint * sky_scale + sc.fill;
    let high = clamp(sun_direction().y, 0.0, 1.0);
    let warm_ground = sun * vec3<f32>(1.0, 0.82, 0.64) * toon.look_light.y * high;
    let ground = mix(sc.fill * 0.35, warm_ground, warm);
    return mix(ground, sky, clamp(N.y * 0.5 + 0.5, 0.0, 1.0));
}

// `shadow_of` for the look-dev light: skin's shadow moves toward warm peach-rose when the key light
// is warm (noon/dusk), and stays harmonized with the cool scene hue under blue moonlight at night.
fn ld_shadow_of(lit: vec3<f32>, value: f32, scene_hue: f32, warm: f32) -> vec3<f32> {
    var hsv = rgb_to_hsv(lit);
    let skin = is_kind(1.0) || is_kind(2.0);
    let hair = is_kind(4.0);
    let own = select(0.0, smoothstep(0.12, 0.35, hsv.y), hair);
    if (skin) {
        var d_warm = 0.008 - hsv.x;
        d_warm = d_warm - round(d_warm);
        var d_cool = scene_hue - hsv.x;
        d_cool = d_cool - round(d_cool);
        hsv.x = fract(hsv.x + d_warm * (0.40 * warm) + d_cool * (0.15 * (1.0 - warm)));
        hsv.y = clamp(hsv.y * mix(1.0, toon.look_light.w, warm), 0.0, 1.0);
    } else {
        let red = 1.0 - smoothstep(0.05, 0.12, abs(hsv.x - round(hsv.x)));
        let shift = toon.shade.y * (1.0 - 0.75 * red) * (1.0 - own);
        var d = scene_hue - hsv.x;
        d = d - round(d);
        hsv.x = fract(hsv.x + d * shift);
        let sat = mix(toon.shade.z, max(toon.shade.z, 1.12), own);
        hsv.y = clamp(hsv.y * sat, 0.0, 1.0);
    }
    hsv.z = hsv.z * value;
    return hsv_to_rgb(hsv);
}

// The sun's bands on a character with the look-dev light: its own threshold (a little more of
// the form turns to shadow) and less brush breakup, so cloth reads as clean cel bands.
fn ld_bands(ndl: f32, p: vec3<f32>) -> vec2<f32> {
    let brush = (noise3(p * toon.extra.x) - 0.5) * toon.band.z * toon.look_ramp.y;
    let t = toon.look_ramp.x + brush;
    return vec2<f32>(
        smoothstep(t - toon.band.y, t + toon.band.y, ndl),
        smoothstep(-0.35 + brush, -0.15 + brush, ndl)
    );
}

// `banded` for the look-dev light: the hemisphere instead of the flat fill (kept low on lit planes
// so noon sunlight stays crisp and warm), and warm-gated sun desaturation in shadow so warm sun
// splits against cool sky shadows while cool moonlight keeps 1.0 of its blue colour.
fn ld_banded(albedo: vec3<f32>, sun: vec3<f32>, lit: f32, value: f32, sc: Scene, N: vec3<f32>) -> vec3<f32> {
    let warm = ld_sun_warmth(sun);
    let skin = is_kind(1.0) || is_kind(2.0);
    let lit_color = albedo * sun;
    var sun_keep = mix(1.0, toon.look_ramp.z, warm);
    sun_keep = select(sun_keep, mix(sun_keep, 1.0, 0.4), skin);
    let neutral = albedo * mix(vec3<f32>(luma(sun)), sun, sun_keep);
    let shadow_color = ld_shadow_of(neutral, value, sc.hue, warm) * toon.shadow.rgb + albedo * sun * toon.extra.y;
    let color = mix(shadow_color, lit_color, lit);
    return color + albedo * ld_hemi(N, sun, sc, warm, skin) * mix(1.0, 0.08, lit);
}

// A cel-stepped highlight (Blue Protocol): broader curve so curved metal poles, copper and glass
// catch stylized glints across normal camera angles while tamed peak intensity keeps flat lamp
// roofs from blowing out; none from roughness 0.88 up (cloth, skin, stone).
fn ld_specular(N: vec3<f32>, V: vec3<f32>, L: vec3<f32>, sun: vec3<f32>, lit: f32, albedo: vec3<f32>, rough: f32, metal: f32, k: f32) -> vec3<f32> {
    let gloss = 1.0 - smoothstep(0.5, 0.88, rough);
    if (gloss <= 0.0 || toon.look.z <= 0.0) {
        return vec3<f32>(0.0);
    }
    let H = normalize(L + V);
    let ndh = max(dot(N, H), 0.0);
    let r = clamp(rough, 0.04, 1.0);
    let s = pow(ndh, mix(96.0, 8.0, sqrt(r)));
    let w = mix(0.05, 0.26, r);
    let cel = smoothstep(0.45 - w, 0.45 + w, s);
    let tint = mix(vec3<f32>(1.0, 0.97, 0.92), clamp(albedo * 1.6 + 0.12, vec3<f32>(0.0), vec3<f32>(1.15)), metal);
    return tint * sun * cel * lit * gloss * mix(0.24, 0.52, metal) * k * toon.look.z;
}

// The character rim: an asymmetric, cel-stepped Fresnel crescent on the sunward silhouette (with
// front-lit view projection suppressing double-shoulder halos, a luminance-preserving hair tint so
// dark hair stays rich rather than chalky, and a wider anti-aliased Fresnel band plus upward sky
// separation so Subtle reads cleanly at 8-12 m without 1 px wires on boots). Zero when off.
fn ld_char_rim(N: vec3<f32>, V: vec3<f32>, L: vec3<f32>, sun: vec3<f32>, shadow: f32, albedo: vec3<f32>, sc: Scene, hair: bool) -> vec3<f32> {
    let s = toon.look.y;
    if (s <= 0.0) {
        return vec3<f32>(0.0);
    }
    let fr = fresnel(N, V);
    let fw = fwidth(fr);
    let lv = dot(L, V);
    let l_perp = L - V * max(lv, 0.0);
    let l_len = length(l_perp);
    let l_dir = select(L, l_perp / max(l_len, 1e-4), lv > 0.0);
    let asym = select(1.0, smoothstep(0.08, 0.38, l_len), lv > 0.0);
    let back = smoothstep(0.0, -0.5, lv);
    let side = clamp(smoothstep(0.12, 0.52, dot(N, l_dir)) * asym + back * 0.75, 0.0, 1.0);
    let edge = smoothstep(0.40 - fw, 0.62 + fw, fr);
    let up_key = smoothstep(-0.25, 0.28, N.y);
    let lum_scale = mix(0.50, 1.0, sqrt(clamp(luma(albedo), 0.0, 1.0)));
    let cloth_col = mix(toon.rim.rgb, albedo * 1.4 + vec3<f32>(0.08), 0.22) * lum_scale;
    let hair_col = albedo * 1.55 + toon.rim.rgb * 0.06;
    let col = select(cloth_col, hair_col, hair);
    let key = col * sun * edge * side * up_key * mix(0.30, 1.0, shadow) * 0.72;
    let up_sky = smoothstep(-0.05, 0.50, N.y);
    let far = smoothstep(0.44 - fw, 0.72 + fw, fr) * (1.0 - side * 0.7) * up_sky;
    let hair_sky = select(1.0, mix(0.25, 1.0, sqrt(clamp(luma(albedo), 0.0, 1.0))), hair);
    let sky = hsv_to_rgb(vec3<f32>(sc.hue, 0.45, 1.0)) * luma(sun) * far * hair_sky * 0.24;
    return (key + sky) * s;
}

// Local warm point lights under Look-dev (step 2.2): softer near-bulb falloff (`d2 + 1.4`) so low
// braziers and characters standing beside a street lamp don't clip to white while casting a rich
// warm pool across cobblestones and nearby clothes; gentle highlight shoulder prevents over-bright
// washout where two pools meet.
fn ld_point_lights(albedo: vec3<f32>, p: vec3<f32>, N: vec3<f32>, view_z: f32, frag: vec2<f32>, ortho: bool) -> vec3<f32> {
    var color = vec3<f32>(0.0);
    let cluster = clustered_forward::view_fragment_cluster_index(frag, view_z, ortho);
    let ranges = clustered_forward::unpack_clusterable_object_index_ranges(cluster);
    for (var i: u32 = ranges.first_point_light_index_offset; i < ranges.first_spot_light_index_offset; i = i + 1u) {
        let id = clustered_forward::get_clusterable_object_id(i);
        let l = &view_bindings::clustered_lights.data[id];
        let to = (*l).position_radius.xyz - p;
        let d2 = dot(to, to);
        let f = d2 * (*l).color_inverse_square_range.w;
        let window = clamp(1.0 - f * f, 0.0, 1.0);
        let fall = window * window / (d2 + 1.4);
        let b = smoothstep(-0.15, 0.25, dot(N, normalize(to))) * 0.78 + 0.22;
        color = color + albedo * (*l).color_inverse_square_range.rgb * fall * b * view_bindings::view.exposure / 3.14159265 * toon.extra.w;
    }
    return color / (vec3<f32>(1.0) + color * 0.22);
}
