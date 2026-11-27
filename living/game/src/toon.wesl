// One shading model for everything (docs/GAME_BRIEF.md, "Art direction"): the sun's light in
// two bands with a soft, slightly brushy edge, shadows tinted toward a hue instead of black, a
// rim of light on silhouettes, no realistic specular. Parameters come from the style profile.
// The lighting itself is shared with the ground (toon_light.wesl); this shader adds what models
// have: kinds (skin, faces, hair), recolouring, and painted detail on scenery.

import bevy_pbr::render::{
    pbr_bindings,
    pbr_fragment::pbr_input_from_standard_material,
    pbr_functions::{alpha_discard, visibility_range_dither},
    mesh_functions,
};
import living_game::toon_light::{
    toon, is_kind, hash3, noise3, rgb_to_hsv, hsv_to_rgb, scene, wetted, view_depth, sun_shadow, sun_color,
    bands, banded, puddles, wet_sheen, fresnel, rim_light, point_lights, emission, has_sun, sun_direction, eye, metres_per_pixel,
    ld_band_pair, ld_sun_warmth, ld_value, ld_banded, ld_specular, ld_char_rim, ld_point_lights,
};

@if(PREPASS_PIPELINE)
import bevy_pbr::{
    prepass::io::{VertexOutput, FragmentOutput},
    deferred::functions::deferred_output,
};
@else
import bevy_pbr::render::{
    forward_io::{VertexOutput, FragmentOutput},
    pbr_functions::main_pass_post_lighting_processing,
};

// A face's shadow map (style.rs `ToonExt::face`); a white fallback elsewhere.
@group(constants::MATERIAL_BIND_GROUP) @binding(101)
var face_map: texture_2d<f32>;
@group(constants::MATERIAL_BIND_GROUP) @binding(102)
var face_sampler: sampler;
// The painted surfaces of scenery (style.rs `DetailLayers`; paint.py `--set material`), one
// array that every scenery material shares; a blank fallback elsewhere.
@group(constants::MATERIAL_BIND_GROUP) @binding(103)
var detail_layers: texture_2d_array<f32>;
@group(constants::MATERIAL_BIND_GROUP) @binding(104)
var detail_sampler: sampler;
// The hair's greying palette (style.rs `ToonExt::tints`, characters/compose.rs `HairTints`):
// row 0 the natural colours, row 1 the silvers, as sRGB values; a fallback elsewhere.
@group(constants::MATERIAL_BIND_GROUP) @binding(105)
var hair_tints: texture_2d<f32>;
// A hand-made material's ink map (contract v1.2, docs/HANDMADE_INK.md; style.rs `ToonExt::ink`):
// G the distance to the nearest stroke over `range`, R its width. Sampled through `face_sampler`;
// a fallback, never read, on materials without ink.
@group(constants::MATERIAL_BIND_GROUP) @binding(106)
var ink_map: texture_2d<f32>;

// The surface that a vertex colour's alpha names (living/tools/textures/surfaces.py: surface k
// is (k + 0.5) / 32), or -1 for none (alpha 1).
fn surface_of(a: f32) -> i32 {
    let k = i32(floor(a * 32.0));
    return select(-1, k, k >= 0 && k < 18);
}

// Painted detail of surface `k` at `p` (world), as factors round 1 (rgb) and a height (a, 0.5
// neutral). It is mapped in the model's own frame, turned but not scaled, so tiles keep their
// size in metres and a turned house gets level courses. Built surfaces and rocks (`layers[k].z`
// 1) are mapped flat onto each face, from its true normal: courses run along walls and along a
// roof's eaves, and coplanar faces join seamlessly. Bark and leaves are triplanar from the
// shading normal, so smooth trunks and crowns show no facets. `dpx` and `dpy` are the
// position's screen derivatives (taken in uniform control flow).
fn detail(k: u32, p: vec3<f32>, dpx: vec3<f32>, dpy: vec3<f32>, N: vec3<f32>, instance: u32) -> vec4<f32> {
    let layer = toon.layers[k];
    let m = mesh_functions::get_world_from_local(instance);
    let to_local = transpose(mat3x3<f32>(normalize(m[0].xyz), normalize(m[1].xyz), normalize(m[2].xyz)));
    let q = to_local * (p - m[3].xyz);
    let qx = to_local * dpx;
    let qy = to_local * dpy;
    let s = layer.x;
    let face = cross(qx, qy);
    if (layer.z > 0.5 && dot(face, face) > 1e-14) {
        let n = normalize(face);
        var u = vec3<f32>(1.0, 0.0, 0.0);
        var v = vec3<f32>(0.0, 0.0, 1.0);
        if (abs(n.y) < 0.92) {
            // Across the face level, and down its slope.
            u = normalize(vec3<f32>(n.z, 0.0, -n.x));
            v = cross(n, u);
            v = select(v, -v, v.y > 0.0);
        }
        let uv = vec2<f32>(dot(q, u), dot(q, v)) * s;
        return textureSampleGrad(detail_layers, detail_sampler, uv, k, vec2<f32>(dot(qx, u), dot(qx, v)) * s, vec2<f32>(dot(qy, u), dot(qy, v)) * s);
    }
    let nl = to_local * N;
    var w = pow(abs(nl), vec3<f32>(4.0));
    w = w / max(w.x + w.y + w.z, 1e-4);
    w = max(w - vec3<f32>(0.05), vec3<f32>(0.0));
    w = w / max(w.x + w.y + w.z, 1e-4);
    var t = vec4<f32>(0.0);
    if (w.x > 0.0) {
        t = t + w.x * textureSampleGrad(detail_layers, detail_sampler, vec2<f32>(q.z, -q.y) * s, k, vec2<f32>(qx.z, -qx.y) * s, vec2<f32>(qy.z, -qy.y) * s);
    }
    if (w.y > 0.0) {
        t = t + w.y * textureSampleGrad(detail_layers, detail_sampler, q.xz * s, k, qx.xz * s, qy.xz * s);
    }
    if (w.z > 0.0) {
        t = t + w.z * textureSampleGrad(detail_layers, detail_sampler, vec2<f32>(q.x, -q.y) * s, k, vec2<f32>(qx.x, -qx.y) * s, vec2<f32>(qy.x, -qy.y) * s);
    }
    return t;
}

// How lit a face's texel is, from its shadow map (living/tools/face_normals.py) and the sun's
// horizontal angle round the head: anime faces take one clean shadow shape that sweeps across
// as the light turns, whatever the sun's height. `fwd` is the head's forward (x, z) in world.
fn face_lit(uv: vec2<f32>, fwd: vec2<f32>, L: vec3<f32>) -> f32 {
    let len = length(L.xz);
    if (len < 1e-3) {
        return 1.0;
    }
    let l = L.xz / len;
    let f = fwd / max(length(fwd), 1e-5);
    let r = vec2<f32>(-f.y, f.x);
    let a = acos(clamp(dot(l, f), -1.0, 1.0)) / 3.14159265;
    let m = textureSampleLevel(face_map, face_sampler, uv, 0.0).rg;
    let th = select(m.g, m.r, dot(l, r) >= 0.0);
    // A sun nearly overhead has no meaningful side: the face is lit.
    let overhead = 1.0 - smoothstep(0.04, 0.2, len);
    return max(smoothstep(-toon.face.x, toon.face.x, th - a), overhead);
}

fn remap(c: f32, f: f32) -> f32 {
    return select(c * f, 1.0 - (1.0 - c) * (-f), f < 0.0);
}

// The factor that `remap` uses to move a mean `m` to a target `t`.
fn factor(m: f32, t: f32) -> f32 {
    if (t <= m) {
        return select(1.0, t / m, m > 1e-4);
    }
    return -max((1.0 - t) / max(1.0 - m, 1e-4), 1e-4);
}

fn srgb_to_linear(c: vec3<f32>) -> vec3<f32> {
    return select(pow((c + 0.055) / 1.055, vec3(2.4)), c / 12.92, c <= vec3(0.04045));
}

// A palette tag (contract v1.3, characters/palette.rs `tag`): a character's colour (bit 24, not
// a plant's sway, bit 25) whose bits name columns of the material's palette image (bit 27).
fn is_palette(tag: u32) -> bool {
    return (tag & ((1u << 24u) | (1u << 25u) | (1u << 27u))) == ((1u << 24u) | (1u << 27u));
}

// Row `row` of a palette tag's entry, linear: the natural column's and the silver's sRGB values
// mixed by clamp(grey x _GREY), as `recolor` greys hair (rows: shade, mid, light, highlight, ink).
fn palette_row(tag: u32, row: i32, grey_v: f32) -> vec3<f32> {
    let natural = textureLoad(hair_tints, vec2<i32>(i32(tag & 255u), row), 0).rgb;
    let silver = textureLoad(hair_tints, vec2<i32>(i32((tag >> 8u) & 255u), row), 0).rgb;
    let t = clamp(f32((tag >> 16u) & 255u) / 255.0 * grey_v, 0.0, 1.0);
    return srgb_to_linear(mix(natural, silver, t));
}

// A character's own colours on a shared texture: the mean texture colour moves to the recipe's,
// keeping the texture's detail. Characters share their base's materials (so they batch); each
// mesh's tag carries its recipe colour as sRGB bytes with bit 24 set (characters.rs `recolor`).
// Hair that greys lock by lock (bit 26 too, bit 25 clear so it never sways) carries instead its
// natural colour's and its silver's places on the palette (bits 0-7, 8-15) and how grey the
// person is (bits 16-23, 0 to 1); `grey_v` is the vertex's `_GREY` (its second UVs' x). The
// colour is then mix(natural, silver, clamp(grey x _GREY, 0, 1)) in sRGB values
// (docs/CHARACTERS.md, "Long hair, short hair and the hair's shading").
fn recolor(c: vec3<f32>, tag: u32, grey_v: f32) -> vec3<f32> {
    // A palette tag names columns of the material's palette, not a colour (`hand_colours`).
    if (is_palette(tag)) {
        return c;
    }
    var mode = toon.recolor.w;
    var goal = toon.recolor.xyz;
    var mean_hue = toon.recolor_from.xy;
    if (mode > 2.5) {
        if ((tag & (1u << 24u)) == 0u) {
            return c;
        }
        var target_srgb = vec3<f32>(f32(tag & 255u), f32((tag >> 8u) & 255u), f32((tag >> 16u) & 255u)) / 255.0;
        if ((tag & (1u << 26u)) != 0u && (tag & (1u << 25u)) == 0u) {
            let natural = textureLoad(hair_tints, vec2<i32>(i32(tag & 255u), 0), 0).rgb;
            let silver = textureLoad(hair_tints, vec2<i32>(i32((tag >> 8u) & 255u), 1), 0).rgb;
            let t = clamp(f32((tag >> 16u) & 255u) / 255.0 * grey_v, 0.0, 1.0);
            target_srgb = mix(natural, silver, t);
        }
        let t = rgb_to_hsv(srgb_to_linear(target_srgb));
        let m = vec3(toon.recolor_from.x, toon.recolor_from.z, toon.recolor_from.w);
        // Grey textures are tinted; coloured ones have their hues moved.
        if (m.y < 0.12) {
            mode = 2.0;
            goal = vec3(t.x, t.y, factor(m.z, t.z));
        } else {
            mode = 1.0;
            goal = vec3(t.x, factor(m.y, t.y), factor(m.z, t.z));
        }
    }
    if (mode < 0.5) {
        return c;
    }
    var hsv = rgb_to_hsv(c);
    if (mode < 1.5) {
        // Hues gather round the target: a many-coloured garment becomes tones of one colour.
        var d = hsv.x - mean_hue.x;
        d = d - round(d);
        hsv.x = fract(goal.x + d * mean_hue.y + 1.0);
        hsv.y = clamp(remap(hsv.y, goal.y), 0.0, 1.0);
    } else {
        hsv.x = goal.x;
        hsv.y = goal.y;
    }
    hsv.z = clamp(remap(hsv.z, goal.z), 0.0, 1.0);
    return hsv_to_rgb(hsv);
}

// Anime hair light (multiplied by the sun): an "angel ring", a band of highlight round the head
// where the strands (running down the surface, from the crown) are square to the half vector
// (Kajiya-Kay, with the tangent made from the normal and up, shifted to place the band), broken
// into comb teeth along the strands; and a rim in the hair's own lightened colour.
fn hair_light(albedo: vec3<f32>, N: vec3<f32>, V: vec3<f32>, L: vec3<f32>, lit: f32, fr: f32, strand: f32, forward: vec3<f32>, in: VertexOutput) -> vec3<f32> {
    let up = vec3<f32>(0.0, 1.0, 0.0);
    let along = up - N * dot(N, up);
    let T = normalize(along * select(1.0, 0.0, length(along) < 1e-3) + N * toon.hair.z + vec3<f32>(0.0, 1e-4, 0.0));
    // Mostly the view: the ring is a drawn shape that stays in sight, nudged by the light.
    let H = normalize(V * 0.75 + L * 0.25);
    // The lock this point is on: its `_GREY` (the second UVs' x; one number per lock, 1.1 to 6.7
    // on composed hair) and char-4's `_RING` (their y, stored as 1 + _RING; 0 without one).
    var lock = 0.0;
    var mask = -1.0;
@if(VERTEX_UVS_B) {
    lock = in.uv_b.x;
    mask = in.uv_b.y - 1.0;
}
    let has_lock = lock > 1e-3;
    // `_GREY` is one number a lock along it, but neighbouring locks' numbers blend across the
    // triangles between them (smoothly round a head), so the lock is the bin its number falls in
    // (`hair_place.z` bins a unit, about a lock wide): breaks and shifts change in clean steps
    // there, not pixel by pixel.
    let bin = floor(lock * toon.hair_place.z);
    let lh = hash3(vec3<f32>(bin * 1.731, bin * 0.377, 11.0));
    let lh2 = hash3(vec3<f32>(bin * 0.533, 7.0, bin * 1.199));
    // Placed by the view (the band slides with the camera), or at a height: where N·up is
    // `hair_lock.w`, moved up or down a little lock by lock.
    let at = toon.hair_lock.w + select(0.0, (lh2 - 0.5) * 2.0 * toon.hair_lock.y, has_lock);
    // At a height only on char-4's hair, whose normals lean up with height and whose locks carry
    // `_GREY`; other hair (VRoid bases) keeps the view-placed ring at its own width.
    let level = select(0.0, toon.hair_lock.z, has_lock);
    let d = mix(abs(dot(T, H)), abs(N.y - at), level);
    let w = select(toon.hair.y, toon.hair_place.w, toon.hair_lock.z > 0.5 && !has_lock);
    // The band's edge: hard (softness 0) or fading from the band's middle (1). On hair shaded as
    // one smooth shape a hard band reads as a seam across the fringe.
    var ring = 1.0 - smoothstep(w * 0.55 * (1.0 - toon.hair_sheen.x), w, d);
    // Comb teeth: the band's edge breaks along the strands (across the hair's UVs).
@if(VERTEX_UVS_A) {
    let teeth = noise3(vec3<f32>(in.uv.x * toon.hair_sheen.w, in.uv.y * 9.0, 0.0));
    ring = ring * mix(1.0, smoothstep(0.25, 0.5, teeth + (1.0 - d / w) * 0.35), toon.hair_sheen.y);
}
    // The strand picture breaks it: light strands carry the sheen, dark ones lose it.
    ring = ring * mix(1.0, clamp((strand - 0.85) * 2.5, 0.0, 1.5), toon.hair_sheen.z);
    // Where locks part: a share `hair_lock.x` of locks goes without it (0.25: one in four).
    ring = ring * select(1.0, step(toon.hair_lock.x, lh), has_lock);
    // Fainter in shadow.
    ring = ring * mix(0.25, 1.0, lit);
    // Where it may lie: char-4's `_RING` when the file has one (1 over the crown band, 0 on
    // fringes, tips, inner surfaces and under caps); else on the upper, outward side of the hair
    // (from `hair_place.x` up)
    if (mask > -0.5) {
        ring = ring * clamp(mask, 0.0, 1.0);
    } else {
        ring = ring * smoothstep(toon.hair_place.x, toon.hair_place.x + 0.25, N.y);
        // and off surfaces that face the character's forward (a fringe).
        ring = ring * (1.0 - smoothstep(toon.hair_place.y, toon.hair_place.y + 0.3, dot(N, forward)));
    }
    // Lighter in the hair's own hue; the lift keeps that hue, so dark hair shows a coloured ring
    // rather than a grey one.
    let lifted = albedo * 1.3 + 0.08 * albedo / max(max(albedo.r, max(albedo.g, albedo.b)), 1e-3);
    // A little paler than the hair, so a ring on brown or orange hair reads as light, not as a
    // more saturated stain.
    let light = mix(lifted, vec3<f32>(dot(lifted, vec3<f32>(0.3, 0.59, 0.11))), 0.35);
    // Pale hair needs less added light to show a ring (and would clip).
    let room = clamp(1.1 - dot(albedo, vec3<f32>(0.3, 0.59, 0.11)) * 1.2, 0.25, 1.0);
@if(LOOKDEV) {
    // Under Look-dev, ld_char_rim owns the hair rim so hair is never double-rimmed.
    return light * ring * toon.hair.x * room;
} @else {
    // The rim stays off surfaces facing down (bang undersides), which it lit like plastic.
    let rim = pow(fr, 3.0) * toon.hair.w * (0.3 + 0.7 * lit) * smoothstep(-0.25, 0.15, N.y);
    return light * ring * toon.hair.x * room + (albedo + vec3<f32>(0.04)) * rim;
}
}

// The character's forward, level: the mesh's world frame turned by the character's root (its
// body's facing; a head turned aside is not followed). Our character files face -Z in their own
// frame (VRM's convention), their roots turned to face +Z. A hand-made file says which way it
// faces (`extras.slop.forward`); the client works that out in each mesh's own frame
// (handmade.rs `local_forward`, in `toon.file`), whatever its nodes turn.
fn facing(in: VertexOutput) -> vec3<f32> {
    let m = mesh_functions::get_world_from_local(in.instance_index);
    let own = select(vec3<f32>(0.0, 0.0, -1.0), toon.file.xyz, toon.file.w > 0.5);
    let f = (m * vec4<f32>(own, 0.0)).xyz;
    let flat = vec3<f32>(f.x, 0.0, f.z);
    return select(normalize(flat), vec3<f32>(0.0, 0.0, 1.0), length(flat) < 1e-4);
}

// The strand picture's own light at this point against its mean across the strands (a few taps
// along u, where the strands vary): about 1 on average, above on light strands. 1 without UVs.
// The taps read the mip the pixel's footprint selects (`duv`: the UV's screen derivatives, x/y
// then z/w, taken in uniform control flow): strands finer than a pixel average out, so their
// contrast fades at a distance instead of shimmering from frame to frame as mip 0 did.
fn strand_light(in: VertexOutput, duv: vec4<f32>) -> f32 {
    var s = 1.0;
@if(VERTEX_UVS_A && !BINDLESS) {
    let lum = vec3<f32>(0.3, 0.59, 0.11);
    let here = dot(textureSampleGrad(pbr_bindings::base_color_texture, pbr_bindings::base_color_sampler, in.uv, duv.xy, duv.zw).rgb, lum);
    var mean = 0.0;
    for (var i = -3; i <= 3; i++) {
        mean += dot(textureSampleGrad(pbr_bindings::base_color_texture, pbr_bindings::base_color_sampler, in.uv + vec2<f32>(f32(i) * 0.012, 0.0), duv.xy, duv.zw).rgb, lum);
    }
    s = here / max(mean / 7.0, 1e-3);
}
    return s;
}

// A threshold `t` on `x` with a half-width `w`, never narrower than the pixel (`fw`, the screen
// derivative of x): clean bands without stair steps.
fn aa(t: f32, w: f32, x: f32, fw: f32) -> f32 {
    let ww = max(max(w, fw), 1e-4);
    return smoothstep(t - ww, t + ww, x);
}

// A hand-made file's hair (style.rs `Kind::HandHair`, docs/HANDMADE_HAIR.md, "The hair profile"):
// at most three flat levels from two thresholds on N·L, the shade colour in cast shadow, and one
// broad highlight where its mask (the larger of the second UVs' y as 1 + _HIGHLIGHT and the mask
// texture's R) passes 0.5, only where the sun reaches; and, v1.1, the lock ink lines from the
// texture's G (a distance field in UV, "Lock ink lines"). `duv` is the UV's screen derivatives,
// taken in uniform control flow; `view_z` the point's view depth.
struct HandColours {
    shade: vec3<f32>,
    mid: vec3<f32>,
    light: vec3<f32>,
    highlight: vec3<f32>,
    ink: vec3<f32>,
}

// A profile's colours (linear): its own (`toon.hand`, `toon.hand_ink`), or, on a palette material
// (contract v1.3) whose mesh carries a palette tag, its entry for the person's hair colour.
fn hand_colours(tag: u32, grey_v: f32) -> HandColours {
    if (toon.palette.x > 0.5 && is_palette(tag)) {
        return HandColours(palette_row(tag, 0, grey_v), palette_row(tag, 1, grey_v), palette_row(tag, 2, grey_v), palette_row(tag, 3, grey_v), palette_row(tag, 4, grey_v));
    }
    return HandColours(toon.hand[0].rgb, toon.hand[1].rgb, toon.hand[2].rgb, toon.hand[3].rgb, toon.hand_ink.rgb);
}

struct HandHair {
    // The base colour, before the light.
    base: vec3<f32>,
    // How far the point is out of shade (0 in the shade band and in cast shadow).
    s1: f32,
    // How much of the pixel the ink line covers.
    ink: f32,
}

// A pixel's metres at the Near stop (view.rs: 8 m up at 58°, 9.43 m away, FOV 42°, 900 px tall):
// `ink_px` is the line's width there.
const INK_NEAR_M_PX: f32 = 0.00805;

// How much of the pixel an ink line covers (docs/HANDMADE_INK.md, "What the client computes";
// the hair's v1.1 lines and every v1.2 ink). `g` is the distance field (G, the distance over
// `range`), `r` the stroke's width (R); `mode` 1 "px" (full width), 2 "px" with taper (R the
// width fraction), 3 "uv" (R the half-width over `range`); `w` px ("px") or min_px ("uv");
// `m_uv` the texel density (metres per UV, 0 unknown); `duv` the UV's screen derivatives.
fn ink_cover(g: f32, r: f32, range: f32, mode: f32, w: f32, fade: f32, m_uv: f32, duv: vec4<f32>, view_z: f32) -> f32 {
    if (g >= 1.0) {
        return 0.0;
    }
    // The UV a pixel spans (its longer side): the distance in pixels.
    let fw_uv = max(max(length(duv.xy), length(duv.zw)), 1e-7);
    let d_px = g * range / fw_uv;
    // The width and the fade follow the pixel's size at its depth and the texel density, which
    // are smooth on screen: screen derivatives step between pixel quads, and a width or fade
    // driven by them flickered as the camera moved.
    let m_px = max(metres_per_pixel(view_z), 1e-6);
    var width = w * min(INK_NEAR_M_PX / m_px, 4.0);
    if (mode > 1.5 && mode < 2.5) {
        width = width * r;
    }
    if (mode > 2.5) {
        // "uv": the stroke's own half-width (R x range) in the world, in pixels, with a floor;
        // nothing at a tip.
        // (Mode 4, `LIVING_GAME_PERF=inkfw`: through the screen derivatives, as the distance.)
        let hw = select(r * range / fw_uv, r * range * m_uv / m_px, m_uv > 0.0 && mode < 3.5);
        width = select(0.0, max(2.0 * hw, w), r > 0.0);
    }
    // How much of the pixel (a 1-pixel box across the line) a line `width` wide covers: it sums
    // to the width across the line whatever its place in the pixels, so a thin line moving by a
    // fraction of a pixel neither flickers nor crawls.
    var cov = clamp(min(d_px + 0.5, width * 0.5) - max(d_px - 0.5, -width * 0.5), 0.0, 1.0);
    // Neighbouring lines' spacing on screen, estimated as 2 · range (the field's range is half
    // the narrowest spacing): fade before they would merge. 0 never fades.
    let space = select(2.0 * range / fw_uv, 2.0 * range * m_uv / m_px, m_uv > 0.0);
    if (fade > 0.0) {
        cov = cov * smoothstep(fade, 2.0 * fade, space);
    }
    return cov;
}

fn hand_hair(N: vec3<f32>, L: vec3<f32>, vis: f32, in: VertexOutput, duv: vec4<f32>, view_z: f32, hc: HandColours) -> HandHair {
    let ndl = dot(N, L);
    let fw = fwidth(ndl);
    let t = toon.hand_bands;
    let s1 = aa(t.x, t.z, ndl, fw) * vis;
    let s2 = aa(t.y, t.z, ndl, fw);
    var level = mix(hc.shade, mix(hc.mid, hc.light, s2), s1);
    var mask = -1.0;
@if(VERTEX_UVS_B) {
    mask = in.uv_b.y - 1.0;
}
    var cov = 0.0;
@if(VERTEX_UVS_A) {
    if (toon.hand[3].w > 0.5) {
        // One tap for all: R the highlight, G the ink field, B the strands.
        let tex = textureSampleGrad(face_map, face_sampler, in.uv, duv.xy, duv.zw);
        mask = max(mask, tex.r);
        // The strands (contract v1.3.1, the profile's `strands`, hand[0].w): a low-contrast
        // modulation of the three bands, 2 x B (0.5 none). It shades within a band, under the
        // highlight and the ink, and adds no gloss. Off, B is ignored.
        level = level * select(1.0, 2.0 * tex.b, toon.hand[0].w > 0.5);
        if (toon.hand_ink_range.z > 0.5) {
            // The v1.1 lock lines: full width, the texel density measured from the mesh.
            cov = ink_cover(tex.g, 1.0, toon.hand_ink_range.x, 1.0, toon.hand_ink.w, toon.hand_ink_range.y, toon.hand_ink_range.w, duv, view_z);
        }
    }
}
    let fm = fwidth(mask);
    let h = select(0.0, aa(0.5, t.w, mask, fm), mask >= 0.0) * s1;
    return HandHair(mix(level, hc.highlight, h), s1, cov);
}

@fragment
fn fragment(
    in: VertexOutput,
    @builtin(front_facing) is_front: bool,
) -> FragmentOutput {
@if(VISIBILITY_RANGE_DITHER)
    visibility_range_dither(in.position, in.visibility_range_dither);
    var pbr_input = pbr_input_from_standard_material(in, is_front);
    pbr_input.material.base_color = alpha_discard(
        pbr_input.material.flags,
        pbr_input.material.alpha_cutoff,
        pbr_input.material.base_color
    );
    var out: FragmentOutput;
@if(PREPASS_PIPELINE) {
    out = deferred_output(in, pbr_input);
} @else {
    let tag = mesh_functions::get_tag(in.instance_index);
    var grey_v = 0.0;
@if(VERTEX_UVS_B)
    grey_v = in.uv_b.x;
    var albedo = vec4<f32>(recolor(pbr_input.material.base_color.rgb, tag, grey_v), pbr_input.material.base_color.a);
    // A tint layer (style.rs `Kind::Tint`) is a factor over the lit skin under it, blended by
    // multiplying (`AlphaMode::Multiply`: dst × mix(1, rgb, a), so premultiplied here), so it
    // carries that skin's light and shadow and never glows on a shaded cheek.
    if (is_kind(6.0)) {
        out.color = vec4<f32>(albedo.rgb * albedo.a, albedo.a);
        return out;
    }
    let N = normalize(pbr_input.N);
    let p = pbr_input.world_position;
    // In uniform control flow: the gradients that painted detail samples with.
    let dpx = dpdx(p.xyz);
    let dpy = dpdy(p.xyz);
    var duv = vec4<f32>(0.0);
@if(VERTEX_UVS_A) {
    duv = vec4<f32>(dpdx(in.uv), dpdy(in.uv));
}
    // Painted detail on generated scenery, under the vertex colours, fading out with distance so
    // the far view stays calm. `relief` is how far its height moves the sun's band edge.
    var relief = 0.0;
@if(VERTEX_COLORS) {
    let k = surface_of(in.color.a);
    let amount = toon.atmo.z * (1.0 - smoothstep(toon.detail.z, toon.detail.w, distance(p.xyz, eye())));
    let a = select(0.0, amount * toon.layers[max(k, 0)].y, toon.detail.x > 0.5 && k >= 0);
    if (a > 0.0) {
        let d = detail(u32(k), p.xyz, dpx, dpy, N, in.instance_index);
        albedo = vec4<f32>(albedo.rgb * mix(vec3<f32>(1.0), d.rgb * 2.0, a), albedo.a);
        relief = (d.a - 0.5) * a * toon.atmo.w;
    }
}
    let sc = scene();
    albedo = vec4<f32>(wetted(albedo.rgb, N), albedo.a);
    let V = normalize(pbr_input.V);
    let view_z = view_depth(p);

    if (has_sun()) {
        let L = sun_direction();
        // A face looks up its shadow a hand's width in front of it (along its flattened normal):
        // bangs then cast no blotches across it, while a roof or a wall still shades the whole
        // face. Eyes keep the plain lookup; their normals point into the head.
        let lift = select(0.0, 0.12, is_kind(2.0));
        let shadow = sun_shadow(vec4<f32>(p.xyz + N * lift, p.w), pbr_input.world_normal, view_z, in.position.xy);
        let sun = sun_color();
        // The look-dev light (style.rs `Look`, shader def LOOKDEV; `toon_light.wesl` `ld_*`):
        // characters' own ramp, its shadow depth and hemisphere fill, the character rim, less rim
        // on scenery and a cel-stepped specular. Without it, every line is as before.
@if(LOOKDEV)
        let b = ld_band_pair(dot(N, L), relief, p.xyz);
@else
        let b = bands(dot(N, L) + relief, p.xyz);
        var band = b.x;
        // Faces take their shadow from their map; eyes, brows, lashes and mouth only from what
        // casts a shadow on them (anime draws them unshaded).
        let face = is_kind(2.0);
        let part = is_kind(3.0);
@if(VERTEX_UVS_A && VERTEX_UVS_B) {
        if (face) {
            band = face_lit(in.uv, in.uv_b, L);
        }
}
        if (part) {
            band = 1.0;
        }
        let lit = band * shadow;
        // A darker core band where the surface turns fully away.
        let away = mix(toon.extra.z, 1.0, b.y);
        // Skin shadows are much lighter (anime faces stay clean), and its far side isn't darkened.
        let skin = is_kind(1.0) || face;
        var depth = select(toon.shadow.a, toon.shadow.a * 0.45, skin);
        depth = select(depth, depth * toon.face.y, face);
        depth = select(depth, toon.shadow.a * toon.face.z, part);
        let value = (1.0 - depth) * select(away, 1.0, skin || part);
@if(LOOKDEV)
        var color = ld_banded(albedo.rgb, sun, lit, ld_value(depth, away, skin, part, ld_sun_warmth(sun)), sc, N);
@else
        var color = banded(albedo.rgb, sun, lit, value, sc);
        // A hand-made hair profile replaces the hair's colour and its banding.
        let hand = is_kind(5.0);
        var lit_albedo = albedo.rgb;
        if (hand) {
            let hc = hand_colours(tag, grey_v);
            let hh = hand_hair(N, L, shadow, in, duv, view_z, hc);
            color = hh.base * sun + hh.base * sc.fill * mix(1.0, 0.45, hh.s1);
            // The ink takes the shade band's light wherever it falls.
            let ink = hc.ink;
            color = mix(color, ink * sun + ink * sc.fill, hh.ink);
            lit_albedo = mix(hh.base, ink, hh.ink);
        }
        // A material's general ink (contract v1.2, docs/HANDMADE_INK.md): an albedo lit exactly
        // as the material lights its own (the same band, cast shadow and depth; a profile hair's
        // shade-band light), laid over the material's own colour (Porter-Duff over: a carrier,
        // whose own alpha is 0, draws only its line). It takes no rim (below).
        var ink_cov = 0.0;
        var out_a = albedo.a;
@if(VERTEX_UVS_A) {
        if (toon.ink_shape.z > 0.5) {
            let t = textureSampleGrad(ink_map, face_sampler, in.uv, duv.xy, duv.zw);
            ink_cov = ink_cover(t.g, t.r, toon.ink_shape.x, toon.ink_shape.z, toon.ink.w, toon.ink_shape.y, toon.ink_shape.w, duv, view_z);
        }
}
        if (ink_cov > 0.0) {
            // A relative ink (v1.3) takes its colour from the mesh's palette entry.
            var ink = toon.ink.rgb;
            if (toon.palette.y > 0.5 && is_palette(tag)) {
                ink = palette_row(tag, 4, grey_v);
            }
@if(LOOKDEV)
            let ink_lit = select(ld_banded(ink, sun, lit, ld_value(depth, away, skin, part, ld_sun_warmth(sun)), sc, N), ink * sun + ink * sc.fill, hand);
@else
            let ink_lit = select(banded(ink, sun, lit, value, sc), ink * sun + ink * sc.fill, hand);
            let a = albedo.a;
            out_a = ink_cov + a * (1.0 - ink_cov);
            color = (ink_lit * ink_cov + color * a * (1.0 - ink_cov)) / max(out_a, 1e-4);
            lit_albedo = (ink * ink_cov + lit_albedo * a * (1.0 - ink_cov)) / max(out_a, 1e-4);
        }
        if (toon.atmo.y > 0.05 && N.y > 0.97 && (tag & (1u << 24u)) == 0u) {
            color = puddles(color, p.xyz, 0.0);
        }
        if (toon.atmo.y > 0.05 && !skin && !part) {
            color = wet_sheen(color, N, V);
        }
        let fr = fresnel(N, V);
        // Hair takes no general rim: its pale cream, added, is several times dark hair's own
        // colour and washes it out. Its one rim is `hair_light`'s, in its own hue (toon.hair.w).
        let rim_strength = select(select(toon.rim.a, toon.face.w, face), 0.0, part || is_kind(4.0) || hand);
@if(LOOKDEV) {
        if (toon.character.x > 0.5) {
            // A character's rim (Settings › Character rim) replaces the classic one, hair too.
            if (!part) {
                let rim_scale = select(1.0, 0.4, face);
                color = color + ld_char_rim(N, V, L, sun, shadow, lit_albedo, sc, hand || is_kind(4.0)) * rim_scale * (1.0 - ink_cov);
            }
        } else {
            // Scenery keeps a little of the classic rim, so characters part from it.
            color = color + rim_light(fr, lit, rim_strength * toon.look.w) * sun * (1.0 - ink_cov);
        }
        if (!part && !hand && !is_kind(4.0)) {
            // A cel-stepped highlight by metallic and roughness; scenery's painted metal, copper
            // and glass (style.rs `Surface`) take their own.
            var rough = pbr_input.material.perceptual_roughness;
            var metal = pbr_input.material.metallic;
            var spec_k = 1.0;
@if(VERTEX_COLORS) {
            if (toon.detail.x > 0.5) {
                let sk = surface_of(in.color.a);
                if (sk == 11) {
                    rough = 0.3;
                    metal = 0.85;
                } else if (sk == 12) {
                    rough = 0.34;
                    metal = 0.9;
                } else if (sk == 15) {
                    rough = 0.12;
                    metal = 0.0;
                    spec_k = 1.8;
                }
            }
}
            color = color + ld_specular(N, V, L, sun, lit, lit_albedo, rough, metal, spec_k) * (1.0 - ink_cov);
        }
}
@else
        color = color + rim_light(fr, lit, rim_strength) * sun * (1.0 - ink_cov);
        if (is_kind(4.0)) {
            color = color + hair_light(albedo.rgb, N, V, L, lit, fr, strand_light(in, duv), facing(in), in) * sun * (1.0 - ink_cov);
        }
@if(LOOKDEV)
        color = color + ld_point_lights(lit_albedo, p.xyz, N, view_z, pbr_input.frag_coord.xy, pbr_input.is_orthographic);
@else
        color = color + point_lights(lit_albedo, p.xyz, N, view_z, pbr_input.frag_coord.xy, pbr_input.is_orthographic);
        color = color + emission(pbr_input.material.emissive.rgb, sc);
        out.color = vec4<f32>(color, out_a);
    } else {
        out.color = vec4<f32>(select(albedo.rgb, hand_colours(tag, grey_v).shade, is_kind(5.0)) * toon.extra.y, albedo.a);
    }
    out.color = main_pass_post_lighting_processing(pbr_input, out.color);
}
    return out;
}
