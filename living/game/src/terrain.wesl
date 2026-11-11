// The ground (terrain.rs): hand-painted detail layers multiplied into the vertex colours, lit by
// the shared toon model (toon_light.wesl, as plain surfaces). Main pass only; the prepass and
// shadows use Bevy's default shaders. `toon` holds the same parameters as the toon materials
// (terrain.rs `sync`). Blocking rock comes from the vertex colour's alpha and reads as cliff.

import bevy_pbr::render::{
    pbr_fragment::pbr_input_from_standard_material,
    mesh_view_bindings as view_bindings,
    mesh_functions,
    view_transformations::position_world_to_clip,
    forward_io::{VertexOutput, FragmentOutput},
    pbr_functions::main_pass_post_lighting_processing,
};
import living_game::toon_light::{
    toon, hash3, scene, wetted, view_depth, sun_shadow, sun_color, bands, banded, puddles, wet_sheen, fresnel, rim_light,
    point_lights, emission, has_sun, sun_direction,
};

// terrain.rs `GroundParams`.
struct Ground {
    // Per layer, 1 / tile size (1/m), four layers per vector (25 layers: 7 vectors).
    scale: array<vec4<f32>, 7>,
    // Per layer, detail strength.
    amount: array<vec4<f32>, 7>,
    // x: full detail until (m), y: none from (m), z: macro variation, w: 1 on, 0 plain look.
    fade: vec4<f32>,
    // x: height-blend depth, y: N.y below which slopes turn to rock, z: N.y of all rock,
    // w: triplanar sharpness.
    blend: vec4<f32>,
}

@group(constants::MATERIAL_BIND_GROUP) @binding(101)
var<uniform> ground: Ground;
@group(constants::MATERIAL_BIND_GROUP) @binding(102)
var layers: texture_2d_array<f32>;
@group(constants::MATERIAL_BIND_GROUP) @binding(103)
var layer_sampler: sampler;

const ROCK: u32 = 6u;
// Blocking rock (terrain.rs `Layer::Cliff`): its weight is the vertex alpha, not a blend weight.
const CLIFF: u32 = 24u;
const LAYERS: u32 = 25u;
// terrain.rs `BLOCKED_ALPHA`: the vertex alpha where every tile round a vertex blocks.
const BLOCKED_ALPHA: f32 = 0.5;
// Cliff stone (linear; sRGB about 92, 86, 82), its strata's bed height (m), and the rim's
// darkening where it meets walkable ground.
const CLIFF_STONE: vec3<f32> = vec3<f32>(0.107, 0.093, 0.084);
const CLIFF_BED: f32 = 1.7;
const CLIFF_RIM: f32 = 0.45;

struct GroundVertex {
    @builtin(instance_index) instance_index: u32,
    @location(0) position: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(5) color: vec4<f32>,
    @location(8) blend_a: vec4<f32>,
    @location(9) blend_b: vec4<f32>,
    @location(10) blend_c: vec4<f32>,
    @location(11) blend_d: vec4<f32>,
    @location(12) blend_e: vec4<f32>,
    @location(13) blend_f: vec4<f32>,
}

struct GroundOut {
    @builtin(position) position: vec4<f32>,
    @location(0) world_position: vec4<f32>,
    @location(1) world_normal: vec3<f32>,
    @location(5) color: vec4<f32>,
    @location(6) @interpolate(flat) instance_index: u32,
    @location(8) blend_a: vec4<f32>,
    @location(9) blend_b: vec4<f32>,
    @location(10) blend_c: vec4<f32>,
    @location(11) blend_d: vec4<f32>,
    @location(12) blend_e: vec4<f32>,
    @location(13) blend_f: vec4<f32>,
}

@vertex
fn vertex(v: GroundVertex) -> GroundOut {
    var out: GroundOut;
    let world_from_local = mesh_functions::get_world_from_local(v.instance_index);
    out.world_position = mesh_functions::mesh_position_local_to_world(world_from_local, vec4<f32>(v.position, 1.0));
    out.position = position_world_to_clip(out.world_position.xyz);
    out.world_normal = mesh_functions::mesh_normal_local_to_world(v.normal, v.instance_index);
    out.color = v.color;
    out.instance_index = v.instance_index;
    out.blend_a = v.blend_a;
    out.blend_b = v.blend_b;
    out.blend_c = v.blend_c;
    out.blend_d = v.blend_d;
    out.blend_e = v.blend_e;
    out.blend_f = v.blend_f;
    return out;
}

// 2D value noise for the macro layer.
fn noise2(p: vec2<f32>) -> f32 {
    let i = floor(p);
    let f = fract(p);
    let u = f * f * (3.0 - 2.0 * f);
    let a = hash3(vec3<f32>(i, 7.0));
    let b = hash3(vec3<f32>(i + vec2(1.0, 0.0), 7.0));
    let c = hash3(vec3<f32>(i + vec2(0.0, 1.0), 7.0));
    let d = hash3(vec3<f32>(i + vec2(1.0, 1.0), 7.0));
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

fn layer_scale(k: u32) -> f32 {
    return ground.scale[k / 4u][k % 4u];
}

fn layer_amount(k: u32) -> f32 {
    return ground.amount[k / 4u][k % 4u];
}

// One layer, projected from the sides that face it (`bw`: x, y, z weights). Gradients come from
// the caller, so sampling inside branches is allowed and mips stay right. Each layer's top
// projection is turned by its own angle, so layers' strokes never line up with the world axes
// or with each other.
fn sample_layer(k: u32, p: vec3<f32>, dpx: vec3<f32>, dpy: vec3<f32>, bw: vec3<f32>) -> vec4<f32> {
    let s = layer_scale(k);
    // The cliff keeps the turn and patches it had as layer 12, before the arid and the authored
    // towns' layers came.
    let kf = select(f32(k), 12.0, k == CLIFF);
    let a = kf * 2.39996 + 0.6;
    let r = mat2x2<f32>(cos(a), sin(a), -sin(a), cos(a));
    var t = vec4<f32>(0.0);
    if (bw.y > 0.0) {
        // Against tiling: patches of about three tiles switch between two variants of the layer
        // (another scale, angle and offset). Away from a patch's edge only one is sampled.
        let mv = smoothstep(0.38, 0.62, noise2(p.xz * s * 0.37 + vec2<f32>(kf * 7.1, 3.3)));
        var top = vec4<f32>(0.0);
        if (mv < 1.0) {
            top = top + (1.0 - mv) * textureSampleGrad(layers, layer_sampler, r * p.xz * s, k, r * dpx.xz * s, r * dpy.xz * s);
        }
        if (mv > 0.0) {
            let s2 = s * 0.77;
            let b = a + 2.1;
            let r2 = mat2x2<f32>(cos(b), sin(b), -sin(b), cos(b));
            top = top + mv * textureSampleGrad(layers, layer_sampler, r2 * p.xz * s2 + vec2<f32>(0.31, 0.57), k, r2 * dpx.xz * s2, r2 * dpy.xz * s2);
        }
        t = t + bw.y * top;
    }
    if (bw.x > 0.0) {
        t = t + bw.x * textureSampleGrad(layers, layer_sampler, vec2<f32>(p.z, -p.y) * s, k, vec2<f32>(dpx.z, -dpx.y) * s, vec2<f32>(dpy.z, -dpy.y) * s);
    }
    if (bw.z > 0.0) {
        t = t + bw.z * textureSampleGrad(layers, layer_sampler, vec2<f32>(p.x, -p.y) * s, k, vec2<f32>(dpx.x, -dpx.y) * s, vec2<f32>(dpy.x, -dpy.y) * s);
    }
    return t;
}

@fragment
fn fragment(g: GroundOut, @builtin(front_facing) is_front: bool) -> FragmentOutput {
    var vo: VertexOutput;
    vo.position = g.position;
    vo.world_position = g.world_position;
    vo.world_normal = g.world_normal;
@if(VERTEX_COLORS)
    vo.color = g.color;
@if(VERTEX_OUTPUT_INSTANCE_INDEX)
    vo.instance_index = g.instance_index;
    var pbr_input = pbr_input_from_standard_material(vo, is_front);
    var out: FragmentOutput;
    var albedo = pbr_input.material.base_color.rgb;
    let N = normalize(pbr_input.N);
    let p = pbr_input.world_position;
    // In uniform control flow: the gradients every layer samples with.
    let dpx = dpdx(p.xyz);
    let dpy = dpdy(p.xyz);
    let dist = distance(p.xyz, view_bindings::view.world_position.xyz);
    let on = ground.fade.w;
    let fade = (1.0 - smoothstep(ground.fade.x, ground.fade.y, dist)) * on;

    // Macro variation: slow value and hue drift (tens of metres), near and far.
    let m = noise2(p.xz / 37.0) * 0.6 + noise2(p.xz / 13.0 + 17.0) * 0.4;
    let mh = noise2(p.xz / 61.0 + 5.0) - 0.5;
    albedo = albedo * (1.0 + on * ground.fade.z * (m - 0.5) * 2.0) * (vec3<f32>(1.0) + on * ground.fade.z * mh * vec3<f32>(0.8, 0.1, -1.0));

    // Blocking rock: the share of blocking tiles round the vertex, its edge pushed about by noise
    // so it doesn't follow the 1 m tiles' steps, then sharpened into a hard boundary at 0.5.
    let blocked = clamp((1.0 - g.color.a) / (1.0 - BLOCKED_ALPHA), 0.0, 1.0);
    var edge = 0.0;
    if (blocked > 0.0) {
        edge = blocked + (noise2(p.xz * 0.9) - 0.5) * 0.5 + (noise2(p.xz * 2.7 + 11.0) - 0.5) * 0.25;
    }
    let cliff = smoothstep(0.42, 0.58, edge);
    if (blocked > 0.0) {
        // Bedded stone on steep faces: a dark seam at the foot of every bed, alternate beds a shade
        // darker, beds of uneven thickness tilting gently across the face. Flat tops show none
        // (seen from above, even beds read as a map's contour lines). Shown at every distance.
        let yw = p.y + 0.55 * sin(p.y * 0.83 + noise2(p.xz / 23.0) * 4.0);
        let sy = yw / CLIFF_BED + noise2(p.xz / 11.0) * 1.2;
        let bedded = 1.0 - smoothstep(0.62, 0.9, N.y);
        let strata = mix(1.0, mix(0.76, 1.0, smoothstep(0.0, 0.16, fract(sy))) * mix(1.0, 0.9, step(0.5, fract(sy * 0.5))), bedded);
        albedo = mix(albedo, mix(CLIFF_STONE, albedo * 0.55, 0.25) * strata, cliff);
        // A dark rim along the boundary, on both sides of it.
        let rim = smoothstep(0.30, 0.42, edge) * (1.0 - smoothstep(0.50, 0.64, edge));
        albedo = albedo * (1.0 - CLIFF_RIM * rim);
    }

    // Detail: the strongest four layers here, blended by their height channel.
    var height = 0.5;
    if (fade > 0.0) {
        var w = array<f32, 25>(
            g.blend_a.x, g.blend_a.y, g.blend_a.z, g.blend_a.w, g.blend_b.x, g.blend_b.y, g.blend_b.z, g.blend_b.w,
            g.blend_c.x, g.blend_c.y, g.blend_c.z, g.blend_c.w, g.blend_d.x, g.blend_d.y, g.blend_d.z, g.blend_d.w,
            g.blend_e.x, g.blend_e.y, g.blend_e.z, g.blend_e.w, g.blend_f.x, g.blend_f.y, g.blend_f.z, g.blend_f.w,
            0.0
        );
        // Steep slopes show rock, whatever grows on the flat.
        let steep = 1.0 - smoothstep(ground.blend.z, ground.blend.y, N.y);
        if (steep > 0.0) {
            for (var k = 0u; k < CLIFF; k = k + 1u) {
                w[k] = w[k] * (1.0 - steep);
            }
            w[ROCK] = w[ROCK] + steep;
        }
        // Blocking rock replaces everything else.
        if (cliff > 0.0) {
            for (var k = 0u; k < CLIFF; k = k + 1u) {
                w[k] = w[k] * (1.0 - cliff);
            }
            w[CLIFF] = cliff;
        }
        var ids = array<u32, 4>(0u, 0u, 0u, 0u);
        var ws = array<f32, 4>(0.0, 0.0, 0.0, 0.0);
        for (var k = 0u; k < LAYERS; k = k + 1u) {
            let x = w[k];
            if (x > 0.02) {
                var lo = 0u;
                for (var j = 1u; j < 4u; j = j + 1u) {
                    if (ws[j] < ws[lo]) {
                        lo = j;
                    }
                }
                if (x > ws[lo]) {
                    ws[lo] = x;
                    ids[lo] = k;
                }
            }
        }
        // Triplanar weights: the top alone on gentle ground, the sides only where they matter.
        var bw = pow(abs(N), vec3<f32>(ground.blend.w));
        bw = bw / max(bw.x + bw.y + bw.z, 1e-4);
        bw = max(bw - vec3<f32>(0.06), vec3<f32>(0.0));
        bw = bw / max(bw.x + bw.y + bw.z, 1e-4);
        let depth = ground.blend.x;
        var t = array<vec4<f32>, 4>(vec4<f32>(0.5), vec4<f32>(0.5), vec4<f32>(0.5), vec4<f32>(0.5));
        var a = array<f32, 4>(-9.0, -9.0, -9.0, -9.0);
        var amax = -9.0;
        for (var j = 0u; j < 4u; j = j + 1u) {
            if (ws[j] > 0.0) {
                t[j] = sample_layer(ids[j], p.xyz, dpx, dpy, bw);
                a[j] = ws[j] + t[j].a * depth;
                amax = max(amax, a[j]);
            }
        }
        var acc = vec3<f32>(0.0);
        var hacc = 0.0;
        var bsum = 0.0;
        for (var j = 0u; j < 4u; j = j + 1u) {
            let b = max(a[j] - amax + depth, 0.0);
            acc = acc + mix(vec3<f32>(1.0), t[j].rgb * 2.0, layer_amount(ids[j])) * b;
            hacc = hacc + t[j].a * b;
            bsum = bsum + b;
        }
        if (bsum > 1e-4) {
            albedo = albedo * mix(vec3<f32>(1.0), acc / bsum, fade);
            height = mix(0.5, hacc / bsum, fade);
        }
    }

    let sc = scene();
    albedo = wetted(albedo, N);
    let V = normalize(pbr_input.V);
    let view_z = view_depth(p);

    if (has_sun()) {
        let L = sun_direction();
        let shadow = sun_shadow(p, pbr_input.world_normal, view_z, g.position.xy);
        let sun = sun_color();
        let b = bands(dot(N, L), p.xyz);
        let lit = b.x * shadow;
        let away = mix(toon.extra.z, 1.0, b.y);
        var color = banded(albedo, sun, lit, (1.0 - toon.shadow.a) * away, sc);
        // Puddles gather in the detail's low places: gaps between stones, ruts.
        if (toon.atmo.y > 0.05 && N.y > 0.97) {
            color = puddles(color, p.xyz, (0.5 - height) * 0.15);
        }
        if (toon.atmo.y > 0.05) {
            color = wet_sheen(color, N, V);
        }
        color = color + rim_light(fresnel(N, V), lit, toon.rim.a) * sun;
        color = color + point_lights(albedo, p.xyz, N, view_z, pbr_input.frag_coord.xy, pbr_input.is_orthographic);
        color = color + emission(pbr_input.material.emissive.rgb, sc);
        out.color = vec4<f32>(color, 1.0);
    } else {
        out.color = vec4<f32>(albedo * toon.extra.y, 1.0);
    }
    out.color = main_pass_post_lighting_processing(pbr_input, out.color);
    return out;
}
