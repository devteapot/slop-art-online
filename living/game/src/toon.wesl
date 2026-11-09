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
}

@group(constants::MATERIAL_BIND_GROUP) @binding(100)
var<uniform> toon: Toon;

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
fn shadow_of(lit: vec3<f32>, value: f32) -> vec3<f32> {
    var hsv = rgb_to_hsv(lit);
    // Skin keeps a warm shadow (toward red-orange) instead of the scene's cool target, so faces
    // never turn purple or flushed.
    let skin = toon.shade.w > 0.5;
    let target_hue = select(toon.shade.x, 0.015, skin);
    // Reds and oranges reach a violet target through magenta, which reads as pink roofs and
    // cloth; they take a quarter of the shift and simply deepen instead.
    let red = 1.0 - smoothstep(0.05, 0.12, abs(hsv.x - round(hsv.x)));
    let shift = select(toon.shade.y * (1.0 - 0.75 * red), 0.35, skin);
    var d = target_hue - hsv.x;
    d = d - round(d);
    hsv.x = fract(hsv.x + d * shift);
    hsv.y = clamp(hsv.y * toon.shade.z, 0.0, 1.0);
    hsv.z = hsv.z * value;
    return hsv_to_rgb(hsv);
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
    let albedo = vec4<f32>(recolor(pbr_input.material.base_color.rgb, mesh_functions::get_tag(in.instance_index)), pbr_input.material.base_color.a);
    let N = normalize(pbr_input.N);
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
            shadow = shadows::fetch_directional_shadow(0u, p, pbr_input.world_normal, view_z, in.position.xy);
        }
        // Lambert's 1/π, at the camera's exposure: the sunlit level of a white surface.
        sun = (*light).color.rgb * view_bindings::view.exposure / 3.14159265 * toon.extra.w;
        let ndl = dot(N, L);
        let brush = (noise3(p.xyz * toon.extra.x) - 0.5) * toon.band.z;
        let t = toon.band.x + brush;
        let band = smoothstep(t - toon.band.y, t + toon.band.y, ndl);
        // A darker core band where the surface turns fully away.
        let core = smoothstep(-0.35 + brush, -0.15 + brush, ndl);
        lit = band * shadow;
        let away = mix(toon.extra.z, 1.0, core);
        let lit_color = albedo.rgb * sun;
        // Skin shadows are much lighter (anime faces stay clean), and its far side isn't darkened.
        let skin = toon.shade.w > 0.5;
        let depth = select(toon.shadow.a, toon.shadow.a * 0.45, skin);
        let shadow_color = shadow_of(lit_color, (1.0 - depth) * select(away, 1.0, skin)) * toon.shadow.rgb + albedo.rgb * sun * toon.extra.y;
        var color = mix(shadow_color, lit_color, lit);
        // Rim light on silhouettes, stronger on the lit side.
        let rim = pow(clamp(1.0 - max(dot(N, V), 0.0), 0.0, 1.0), toon.band.w) * toon.rim.a * (0.35 + 0.65 * lit);
        color = color + toon.rim.rgb * sun * rim;
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
        // Emission (fires, lamps) on top.
        color = color + pbr_input.material.emissive.rgb * view_bindings::view.exposure;
        out.color = vec4<f32>(color, albedo.a);
    } else {
        out.color = vec4<f32>(albedo.rgb * toon.extra.y, albedo.a);
    }
    out.color = main_pass_post_lighting_processing(pbr_input, out.color);
}
    return out;
}
