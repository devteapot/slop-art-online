// One shading model for everything (docs/GAME_BRIEF.md, "Art direction"): the sun's light in
// two bands with a soft, slightly brushy edge, shadows tinted toward a hue instead of black, a
// rim of light on silhouettes, no realistic specular. Parameters come from the style profile.

import bevy_pbr::render::{
    pbr_fragment::pbr_input_from_standard_material,
    pbr_functions::alpha_discard,
    mesh_view_bindings as view_bindings,
    shadows,
    mesh_view_types,
    clustered_forward,
    mesh_functions,
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
    // z saturation multiplier, w: 1 on skin (lighter, warmer shadows; see below).
    shade: vec4<f32>,
    // Recolouring (characters.rs): x the target hue, y saturation and z value factors (>= 0
    // scales toward 0; < 0 scales the distance to 1 by -f), w mode: 0 none, 1 shift, 2 tint,
    // 3 per instance (the target colour is in the mesh's tag; see `recolor`).
    recolor: vec4<f32>,
    // x: the texture's mean hue, y: how much of its hue variation stays (mode 1); in mode 3,
    // z and w: the texture's mean saturation and value.
    recolor_from: vec4<f32>,
    // Weather (weather.rs): x wind strength (the vertex shaders sway plants), y wetness.
    atmo: vec4<f32>,
    // Faces: x shadow-edge softness, y face shadow depth (times skin's), z how far eyes and
    // mouth darken in shadow, w face rim.
    face: vec4<f32>,
    // Hair: x angel-ring strength, y ring width, z ring position (tangent shift), w rim.
    hair: vec4<f32>,
}

@group(constants::MATERIAL_BIND_GROUP) @binding(100)
var<uniform> toon: Toon;
// A face's shadow map (style.rs `ToonExt::face`); a white fallback elsewhere.
@group(constants::MATERIAL_BIND_GROUP) @binding(101)
var face_map: texture_2d<f32>;
@group(constants::MATERIAL_BIND_GROUP) @binding(102)
var face_sampler: sampler;

// What the material shades (style.rs `Kind`, in `shade.w`).
fn is_kind(k: f32) -> bool {
    return abs(toon.shade.w - k) < 0.5;
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

// A character's own colours on a shared texture: the mean texture colour moves to the recipe's,
// keeping the texture's detail. Characters share their base's materials (so they batch); each
// mesh's tag carries its recipe colour as sRGB bytes with bit 24 set (characters.rs `recolor`).
fn recolor(c: vec3<f32>, tag: u32) -> vec3<f32> {
    var mode = toon.recolor.w;
    var goal = toon.recolor.xyz;
    var mean_hue = toon.recolor_from.xy;
    if (mode > 2.5) {
        if ((tag & (1u << 24u)) == 0u) {
            return c;
        }
        let target_srgb = vec3<f32>(f32(tag & 255u), f32((tag >> 8u) & 255u), f32((tag >> 16u) & 255u)) / 255.0;
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

// Anime hair light (multiplied by the sun): an "angel ring", a band of highlight round the head
// where the strands (running down the surface, from the crown) are square to the half vector
// (Kajiya-Kay, with the tangent made from the normal and up, shifted to place the band), broken
// into comb teeth along the strands; and a rim in the hair's own lightened colour.
fn hair_light(albedo: vec3<f32>, N: vec3<f32>, V: vec3<f32>, L: vec3<f32>, lit: f32, fresnel: f32, in: VertexOutput) -> vec3<f32> {
    let up = vec3<f32>(0.0, 1.0, 0.0);
    let along = up - N * dot(N, up);
    let T = normalize(along * select(1.0, 0.0, length(along) < 1e-3) + N * toon.hair.z + vec3<f32>(0.0, 1e-4, 0.0));
    // Mostly the view: the ring is a drawn shape that stays in sight, nudged by the light.
    let H = normalize(V * 0.75 + L * 0.25);
    let d = abs(dot(T, H));
    let w = toon.hair.y;
    var ring = 1.0 - smoothstep(w * 0.55, w, d);
    // Comb teeth: the band's edge breaks along the strands (across the hair's UVs).
@if(VERTEX_UVS_A) {
    let teeth = noise3(vec3<f32>(in.uv.x * 90.0, in.uv.y * 9.0, 0.0));
    ring = ring * smoothstep(0.25, 0.5, teeth + (1.0 - d / w) * 0.35);
}
    // Only on the upper, outward side of the hair, and fainter in shadow.
    ring = ring * smoothstep(0.2, 0.45, N.y) * mix(0.25, 1.0, lit);
    // Lighter in the hair's own hue; the lift keeps that hue, so dark hair shows a coloured ring
    // rather than a grey one.
    let lifted = albedo * 1.3 + 0.08 * albedo / max(max(albedo.r, max(albedo.g, albedo.b)), 1e-3);
    // A little paler than the hair, so a ring on brown or orange hair reads as light, not as a
    // more saturated stain.
    let light = mix(lifted, vec3<f32>(dot(lifted, vec3<f32>(0.3, 0.59, 0.11))), 0.35);
    // The rim stays off surfaces facing down (bang undersides), which it lit like plastic.
    let rim = pow(fresnel, 3.0) * toon.hair.w * (0.3 + 0.7 * lit) * smoothstep(-0.25, 0.15, N.y);
    // Pale hair needs less added light to show a ring (and would clip).
    let room = clamp(1.1 - dot(albedo, vec3<f32>(0.3, 0.59, 0.11)) * 1.2, 0.25, 1.0);
    return light * ring * toon.hair.x * room + (albedo + vec3<f32>(0.04)) * rim;
}

@fragment
fn fragment(
    in: VertexOutput,
    @builtin(front_facing) is_front: bool,
) -> FragmentOutput {
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
    var albedo = vec4<f32>(recolor(pbr_input.material.base_color.rgb, tag), pbr_input.material.base_color.a);
    let N = normalize(pbr_input.N);
    // The time of day and the region (daylight.rs) arrive through the scene's ambient light: its
    // colour is the sky's fill (it lifts shadows and dark scenes, and its hue is the shadows'
    // target hue), its alpha how strongly glowing things shine (0: no atmosphere; the
    // material's own shadow hue applies and nothing is lifted).
    let amb = view_bindings::lights.ambient_color;
    let atmo = amb.a > 0.0;
    let fill = select(vec3<f32>(0.0), amb.rgb, atmo);
    let fill_hsv = rgb_to_hsv(fill);
    let scene_hue = select(toon.shade.x, fill_hsv.x, atmo && fill_hsv.y > 0.02);
    let glow = select(1.0, amb.a, atmo);
    // Rain darkens surfaces, upward ones most.
    let wet = toon.atmo.y;
    albedo = vec4<f32>(albedo.rgb * (1.0 - wet * (0.16 + 0.14 * clamp(N.y, 0.0, 1.0))), albedo.a);
    let V = normalize(pbr_input.V);
    let p = pbr_input.world_position;
    let view_z = dot(vec4<f32>(
        view_bindings::view.view_from_world[0].z,
        view_bindings::view.view_from_world[1].z,
        view_bindings::view.view_from_world[2].z,
        view_bindings::view.view_from_world[3].z
    ), p);

    // The sun (first directional light) and its shadow.
    var sun = vec3<f32>(1.0);
    var lit = 0.0;
    if (view_bindings::lights.n_directional_lights > 0u) {
        let light = &view_bindings::lights.directional_lights[0];
        let L = (*light).direction_to_light;
        var shadow = 1.0;
        if (((*light).flags & mesh_view_types::DIRECTIONAL_LIGHT_FLAGS_SHADOWS_ENABLED_BIT) != 0u) {
            // A face looks up its shadow a hand's width in front of it (along its flattened
            // normal): bangs then cast no blotches across it, while a roof or a wall still shades
            // the whole face. Eyes keep the plain lookup; their normals point into the head.
            let lift = select(0.0, 0.12, is_kind(2.0));
            shadow = shadows::fetch_directional_shadow(0u, vec4<f32>(p.xyz + N * lift, p.w), pbr_input.world_normal, view_z, in.position.xy);
        }
        // Lambert's 1/π, at the camera's exposure: the sunlit level of a white surface.
        sun = (*light).color.rgb * view_bindings::view.exposure / 3.14159265 * toon.extra.w;
        let ndl = dot(N, L);
        let brush = (noise3(p.xyz * toon.extra.x) - 0.5) * toon.band.z;
        let t = toon.band.x + brush;
        var band = smoothstep(t - toon.band.y, t + toon.band.y, ndl);
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
        // A darker core band where the surface turns fully away.
        let core = smoothstep(-0.35 + brush, -0.15 + brush, ndl);
        lit = band * shadow;
        let away = mix(toon.extra.z, 1.0, core);
        let lit_color = albedo.rgb * sun;
        // Skin shadows are much lighter (anime faces stay clean), and its far side isn't darkened.
        let skin = is_kind(1.0) || face;
        var depth = select(toon.shadow.a, toon.shadow.a * 0.45, skin);
        depth = select(depth, depth * toon.face.y, face);
        depth = select(depth, toon.shadow.a * toon.face.z, part);
        let shadow_color = shadow_of(lit_color, (1.0 - depth) * select(away, 1.0, skin || part), scene_hue) * toon.shadow.rgb + albedo.rgb * sun * toon.extra.y;
        var color = mix(shadow_color, lit_color, lit);
        // Sky fill: lifts shadows most, so night stays readable.
        color = color + albedo.rgb * fill * mix(1.0, 0.45, lit);
        // Puddles: on wet flat ground, small dark patches that mirror the fog's sky colour, with
        // a light rim.
        if (wet > 0.05 && N.y > 0.97 && (tag & (1u << 24u)) == 0u) {
            let n = noise3(vec3<f32>(p.x * 0.55, 0.0, p.z * 0.55)) * 0.65 + noise3(vec3<f32>(p.x * 1.7, 3.0, p.z * 1.7)) * 0.35;
            let th = 0.77 - 0.05 * wet;
            let puddle = smoothstep(th, th + 0.02, n) * smoothstep(0.05, 0.6, wet);
            let rim = (smoothstep(th - 0.015, th, n) - smoothstep(th + 0.01, th + 0.025, n)) * smoothstep(0.05, 0.6, wet);
@if(DISTANCE_FOG) {
            let sky = view_bindings::fog.base_color.rgb;
            color = mix(color, color * 0.62 + sky * 0.12, puddle);
            color = color + sky * rim * 0.2;
}
        }
        // Rim light on silhouettes, stronger on the lit side.
        let fresnel = clamp(1.0 - max(dot(N, V), 0.0), 0.0, 1.0);
        let rim_strength = select(select(toon.rim.a, toon.face.w, face), 0.0, part);
        let rim = pow(fresnel, toon.band.w) * rim_strength * (0.35 + 0.65 * lit);
        color = color + toon.rim.rgb * sun * rim;
        if (is_kind(4.0)) {
            color = color + hair_light(albedo.rgb, N, V, L, lit, fresnel, in) * sun;
        }
        // Local lights (point lights: lamps, crystals, neon), banded like the sun, no shadows.
        let cluster = clustered_forward::view_fragment_cluster_index(pbr_input.frag_coord.xy, view_z, pbr_input.is_orthographic);
        let ranges = clustered_forward::unpack_clusterable_object_index_ranges(cluster);
        for (var i: u32 = ranges.first_point_light_index_offset; i < ranges.first_spot_light_index_offset; i = i + 1u) {
            let id = clustered_forward::get_clusterable_object_id(i);
            let l = &view_bindings::clustered_lights.data[id];
            let to = (*l).position_radius.xyz - p.xyz;
            let d2 = dot(to, to);
            let f = d2 * (*l).color_inverse_square_range.w;
            let window = clamp(1.0 - f * f, 0.0, 1.0);
            let fall = window * window / max(d2, 0.0001);
            let b = smoothstep(-0.05, 0.12, dot(N, normalize(to))) * 0.8 + 0.2;
            color = color + albedo.rgb * (*l).color_inverse_square_range.rgb * fall * b * view_bindings::view.exposure / 3.14159265 * toon.extra.w;
        }
        // Emission (fires, lamps) on top; it reads stronger at night.
        color = color + pbr_input.material.emissive.rgb * view_bindings::view.exposure * glow;
        out.color = vec4<f32>(color, albedo.a);
    } else {
        out.color = vec4<f32>(albedo.rgb * toon.extra.y, albedo.a);
    }
    out.color = main_pass_post_lighting_processing(pbr_input, out.color);
}
    return out;
}
