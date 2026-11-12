// One shading model for everything (docs/GAME_BRIEF.md, "Art direction"): the sun's light in
// two bands with a soft, slightly brushy edge, shadows tinted toward a hue instead of black, a
// rim of light on silhouettes, no realistic specular. Parameters come from the style profile.
// The lighting itself is shared with the ground (toon_light.wesl); this shader adds what models
// have: kinds (skin, faces, hair), recolouring, and painted detail on scenery.

import bevy_pbr::render::{
    pbr_fragment::pbr_input_from_standard_material,
    pbr_functions::{alpha_discard, visibility_range_dither},
    mesh_functions,
};
import living_game::toon_light::{
    toon, is_kind, noise3, rgb_to_hsv, hsv_to_rgb, scene, wetted, view_depth, sun_shadow, sun_color,
    bands, banded, puddles, wet_sheen, fresnel, rim_light, point_lights, emission, has_sun, sun_direction, eye,
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

// Anime hair light (multiplied by the sun): an "angel ring", a band of highlight round the head
// where the strands (running down the surface, from the crown) are square to the half vector
// (Kajiya-Kay, with the tangent made from the normal and up, shifted to place the band), broken
// into comb teeth along the strands; and a rim in the hair's own lightened colour.
fn hair_light(albedo: vec3<f32>, N: vec3<f32>, V: vec3<f32>, L: vec3<f32>, lit: f32, fr: f32, in: VertexOutput) -> vec3<f32> {
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
    let rim = pow(fr, 3.0) * toon.hair.w * (0.3 + 0.7 * lit) * smoothstep(-0.25, 0.15, N.y);
    // Pale hair needs less added light to show a ring (and would clip).
    let room = clamp(1.1 - dot(albedo, vec3<f32>(0.3, 0.59, 0.11)) * 1.2, 0.25, 1.0);
    return light * ring * toon.hair.x * room + (albedo + vec3<f32>(0.04)) * rim;
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
    var albedo = vec4<f32>(recolor(pbr_input.material.base_color.rgb, tag), pbr_input.material.base_color.a);
    let N = normalize(pbr_input.N);
    let p = pbr_input.world_position;
    // In uniform control flow: the gradients that painted detail samples with.
    let dpx = dpdx(p.xyz);
    let dpy = dpdy(p.xyz);
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
        var color = banded(albedo.rgb, sun, lit, (1.0 - depth) * select(away, 1.0, skin || part), sc);
        if (toon.atmo.y > 0.05 && N.y > 0.97 && (tag & (1u << 24u)) == 0u) {
            color = puddles(color, p.xyz, 0.0);
        }
        if (toon.atmo.y > 0.05 && !skin && !part) {
            color = wet_sheen(color, N, V);
        }
        let fr = fresnel(N, V);
        // Hair takes no general rim: its pale cream, added, is several times dark hair's own
        // colour and washes it out. Its one rim is `hair_light`'s, in its own hue (toon.hair.w).
        let rim_strength = select(select(toon.rim.a, toon.face.w, face), 0.0, part || is_kind(4.0));
        color = color + rim_light(fr, lit, rim_strength) * sun;
        if (is_kind(4.0)) {
            color = color + hair_light(albedo.rgb, N, V, L, lit, fr, in) * sun;
        }
        color = color + point_lights(albedo.rgb, p.xyz, N, view_z, pbr_input.frag_coord.xy, pbr_input.is_orthographic);
        color = color + emission(pbr_input.material.emissive.rgb, sc);
        out.color = vec4<f32>(color, albedo.a);
    } else {
        out.color = vec4<f32>(albedo.rgb * toon.extra.y, albedo.a);
    }
    out.color = main_pass_post_lighting_processing(pbr_input, out.color);
}
    return out;
}
