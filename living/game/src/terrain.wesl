// The ground (terrain.rs): hand-painted detail layers multiplied into the vertex colours, lit by
// the shared toon model. Main pass only; the prepass and shadows use Bevy's default shaders.
//
// The lighting is a copy of toon.wesl's path for plain surfaces (Kind::Plain): keep the two in
// step. `toon` holds the same parameters as the toon materials (terrain.rs `sync`).

import bevy_pbr::render::{
    pbr_fragment::pbr_input_from_standard_material,
    mesh_view_bindings as view_bindings,
    shadows,
    mesh_view_types,
    clustered_forward,
    mesh_functions,
    view_transformations::position_world_to_clip,
    forward_io::{VertexOutput, FragmentOutput},
    pbr_functions::main_pass_post_lighting_processing,
};

// Must match `Toon` in toon.wesl (style.rs `ToonParams`).
struct Toon {
    shadow: vec4<f32>,
    rim: vec4<f32>,
    band: vec4<f32>,
    extra: vec4<f32>,
    shade: vec4<f32>,
    recolor: vec4<f32>,
    recolor_from: vec4<f32>,
    atmo: vec4<f32>,
    face: vec4<f32>,
    hair: vec4<f32>,
}

// terrain.rs `GroundParams`.
struct Ground {
    // Per layer, 1 / tile size (1/m), four layers per vector.
    scale: array<vec4<f32>, 3>,
    // Per layer, detail strength.
    amount: array<vec4<f32>, 3>,
    // x: full detail until (m), y: none from (m), z: macro variation, w: 1 on, 0 plain look.
    fade: vec4<f32>,
    // x: height-blend depth, y: N.y below which slopes turn to rock, z: N.y of all rock,
    // w: triplanar sharpness.
    blend: vec4<f32>,
}

@group(constants::MATERIAL_BIND_GROUP) @binding(100)
var<uniform> toon: Toon;
@group(constants::MATERIAL_BIND_GROUP) @binding(101)
var<uniform> ground: Ground;
@group(constants::MATERIAL_BIND_GROUP) @binding(102)
var layers: texture_2d_array<f32>;
@group(constants::MATERIAL_BIND_GROUP) @binding(103)
var layer_sampler: sampler;

const ROCK: u32 = 6u;

struct GroundVertex {
    @builtin(instance_index) instance_index: u32,
    @location(0) position: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(5) color: vec4<f32>,
    @location(8) blend_a: vec4<f32>,
    @location(9) blend_b: vec4<f32>,
    @location(10) blend_c: vec4<f32>,
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
    return out;
}

fn hash3(p: vec3<f32>) -> f32 {
    let q = fract(p * 0.1031);
    let r = q + dot(q, q.yzx + 33.33);
    return fract((r.x + r.y) * r.z);
}

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

// toon.wesl `shadow_of` for plain surfaces.
fn shadow_of(lit: vec3<f32>, value: f32, scene_hue: f32) -> vec3<f32> {
    var hsv = rgb_to_hsv(lit);
    let red = 1.0 - smoothstep(0.05, 0.12, abs(hsv.x - round(hsv.x)));
    let shift = toon.shade.y * (1.0 - 0.75 * red);
    var d = scene_hue - hsv.x;
    d = d - round(d);
    hsv.x = fract(hsv.x + d * shift);
    hsv.y = clamp(hsv.y * toon.shade.z, 0.0, 1.0);
    hsv.z = hsv.z * value;
    return hsv_to_rgb(hsv);
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
    let a = f32(k) * 2.39996 + 0.6;
    let r = mat2x2<f32>(cos(a), sin(a), -sin(a), cos(a));
    var t = vec4<f32>(0.0);
    if (bw.y > 0.0) {
        // Against tiling: patches of about three tiles switch between two variants of the layer
        // (another scale, angle and offset). Away from a patch's edge only one is sampled.
        let mv = smoothstep(0.38, 0.62, noise2(p.xz * s * 0.37 + vec2<f32>(f32(k) * 7.1, 3.3)));
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

    // Detail: the strongest four layers here, blended by their height channel.
    var height = 0.5;
    if (fade > 0.0) {
        var w = array<f32, 12>(g.blend_a.x, g.blend_a.y, g.blend_a.z, g.blend_a.w, g.blend_b.x, g.blend_b.y, g.blend_b.z, g.blend_b.w, g.blend_c.x, g.blend_c.y, g.blend_c.z, g.blend_c.w);
        // Steep slopes show rock, whatever grows on the flat.
        let steep = 1.0 - smoothstep(ground.blend.z, ground.blend.y, N.y);
        if (steep > 0.0) {
            for (var k = 0u; k < 12u; k = k + 1u) {
                w[k] = w[k] * (1.0 - steep);
            }
            w[ROCK] = w[ROCK] + steep;
        }
        var ids = array<u32, 4>(0u, 0u, 0u, 0u);
        var ws = array<f32, 4>(0.0, 0.0, 0.0, 0.0);
        for (var k = 0u; k < 12u; k = k + 1u) {
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

    let amb = view_bindings::lights.ambient_color;
    let atmo = amb.a > 0.0;
    let fill = select(vec3<f32>(0.0), amb.rgb, atmo);
    let fill_hsv = rgb_to_hsv(fill);
    let scene_hue = select(toon.shade.x, fill_hsv.x, atmo && fill_hsv.y > 0.02);
    let glow = select(1.0, amb.a, atmo);
    // Rain darkens surfaces, upward ones most.
    let wet = toon.atmo.y;
    albedo = albedo * (1.0 - wet * (0.16 + 0.14 * clamp(N.y, 0.0, 1.0)));
    let V = normalize(pbr_input.V);
    let view_z = dot(vec4<f32>(
        view_bindings::view.view_from_world[0].z,
        view_bindings::view.view_from_world[1].z,
        view_bindings::view.view_from_world[2].z,
        view_bindings::view.view_from_world[3].z
    ), p);

    if (view_bindings::lights.n_directional_lights > 0u) {
        let light = &view_bindings::lights.directional_lights[0];
        let L = (*light).direction_to_light;
        var shadow = 1.0;
        if (((*light).flags & mesh_view_types::DIRECTIONAL_LIGHT_FLAGS_SHADOWS_ENABLED_BIT) != 0u) {
            shadow = shadows::fetch_directional_shadow(0u, p, pbr_input.world_normal, view_z, g.position.xy);
        }
        let sun = (*light).color.rgb * view_bindings::view.exposure / 3.14159265 * toon.extra.w;
        let ndl = dot(N, L);
        let brush = (noise3(p.xyz * toon.extra.x) - 0.5) * toon.band.z;
        let th = toon.band.x + brush;
        let band = smoothstep(th - toon.band.y, th + toon.band.y, ndl);
        let core = smoothstep(-0.35 + brush, -0.15 + brush, ndl);
        let lit = band * shadow;
        let away = mix(toon.extra.z, 1.0, core);
        let lit_color = albedo * sun;
        let shadow_color = shadow_of(lit_color, (1.0 - toon.shadow.a) * away, scene_hue) * toon.shadow.rgb + albedo * sun * toon.extra.y;
        var color = mix(shadow_color, lit_color, lit);
        color = color + albedo * fill * mix(1.0, 0.45, lit);
        // Puddles (toon.wesl), gathering in the detail's low places: gaps between stones, ruts.
        if (wet > 0.05 && N.y > 0.97) {
            let n = noise3(vec3<f32>(p.x * 0.55, 0.0, p.z * 0.55)) * 0.65 + noise3(vec3<f32>(p.x * 1.7, 3.0, p.z * 1.7)) * 0.35 + (0.5 - height) * 0.15;
            let pth = 0.77 - 0.05 * wet;
            let puddle = smoothstep(pth, pth + 0.02, n) * smoothstep(0.05, 0.6, wet);
            let prim = (smoothstep(pth - 0.015, pth, n) - smoothstep(pth + 0.01, pth + 0.025, n)) * smoothstep(0.05, 0.6, wet);
@if(DISTANCE_FOG) {
            let sky = view_bindings::fog.base_color.rgb;
            color = mix(color, color * 0.62 + sky * 0.12, puddle);
            color = color + sky * prim * 0.2;
}
        }
        let fresnel = clamp(1.0 - max(dot(N, V), 0.0), 0.0, 1.0);
        let rim = pow(fresnel, toon.band.w) * toon.rim.a * (0.35 + 0.65 * lit);
        color = color + toon.rim.rgb * sun * rim;
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
            color = color + albedo * (*l).color_inverse_square_range.rgb * fall * b * view_bindings::view.exposure / 3.14159265 * toon.extra.w;
        }
        color = color + pbr_input.material.emissive.rgb * view_bindings::view.exposure * glow;
        out.color = vec4<f32>(color, 1.0);
    } else {
        out.color = vec4<f32>(albedo * toon.extra.y, 1.0);
    }
    out.color = main_pass_post_lighting_processing(pbr_input, out.color);
    return out;
}
