// The stylised sky (sky.rs): a gradient from the horizon to the zenith, toon clouds with a hard
// two-tone edge, a sun disc with a stepped halo, a crescent moon, and stars at night. Below the
// horizon it is the fog's colour. Linear HDR output (the sun's core blooms).

import bevy_pbr::render::{
    forward_io::VertexOutput,
    mesh_view_bindings::{view, globals},
};
@if(TONEMAP_IN_SHADER) import bevy_core_pipeline::tonemapping::tone_mapping;

struct Sky {
    zenith: vec4<f32>,
    horizon: vec4<f32>,
    fog: vec4<f32>,
    sun: vec4<f32>,
    moon: vec4<f32>,
    light: vec4<f32>,
    cloud: vec4<f32>,
    time: vec4<f32>,
}

@group(constants::MATERIAL_BIND_GROUP) @binding(0)
var<uniform> sky: Sky;

fn hash2(p: vec2<f32>) -> f32 {
    var q = fract(p * vec2<f32>(123.34, 456.21));
    q = q + dot(q, q + 45.32);
    return fract(q.x * q.y);
}

fn hash3(p: vec3<f32>) -> f32 {
    let q = fract(p * 0.1031);
    let r = q + dot(q, q.yzx + 33.33);
    return fract((r.x + r.y) * r.z);
}

fn noise2(p: vec2<f32>) -> f32 {
    let i = floor(p);
    let f = fract(p);
    let u = f * f * (3.0 - 2.0 * f);
    let a = hash2(i);
    let b = hash2(i + vec2<f32>(1.0, 0.0));
    let c = hash2(i + vec2<f32>(0.0, 1.0));
    let d = hash2(i + vec2<f32>(1.0, 1.0));
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

fn clouds_at(uv: vec2<f32>) -> f32 {
    return noise2(uv) * 0.55 + noise2(uv * 2.3 + 7.1) * 0.3 + noise2(uv * 5.1 + 3.3) * 0.15;
}

@fragment
fn fragment(in: VertexOutput) -> @location(0) vec4<f32> {
    let dir = normalize(in.world_position.xyz - view.world_position.xyz);
    let v = dir.y;
    let zen = sky.zenith.rgb;
    let hor = sky.horizon.rgb;
    let fog = sky.fog.rgb;
    let light = sky.light.rgb;
    let night = sky.light.a;
    let sun = normalize(sky.sun.xyz);
    let moon = normalize(sky.moon.xyz);

    // The gradient, with a slight step a little above the horizon (an anime sky's banding).
    let up = pow(smoothstep(0.0, 0.6, v), 0.65);
    var c = mix(hor, zen, up);
    c = mix(c, mix(hor, zen, up + 0.06), step(0.2, v) * 0.5);
    // Glow round the low sun along the horizon.
    let flat_dir = normalize(vec2<f32>(dir.x, dir.z) + vec2<f32>(1e-5, 0.0));
    let flat_sun = normalize(vec2<f32>(sun.x, sun.z) + vec2<f32>(1e-5, 0.0));
    let low = 1.0 - smoothstep(0.05, 0.45, abs(sun.y));
    let toward = pow(max(dot(flat_dir, flat_sun), 0.0), 5.0);
    c = c + light * toward * low * (1.0 - smoothstep(0.0, 0.4, v)) * 0.35;

    // Stars: one possible star per cell of a fine grid on the sphere, twinkling.
    if (sky.zenith.a > 0.01 && v > 0.0) {
        let p = dir * 160.0;
        let cell = floor(p);
        let h = hash3(cell);
        if (h > 0.972) {
            let at = cell + vec3<f32>(hash3(cell + 1.7), hash3(cell + 3.1), hash3(cell + 5.3));
            let d = length(p - at);
            let tw = 0.65 + 0.35 * sin(globals.time * (1.5 + 3.0 * h) + h * 60.0);
            let s = (1.0 - smoothstep(0.06, 0.16, d)) * tw * smoothstep(0.02, 0.25, v);
            c = c + vec3<f32>(0.85, 0.9, 1.0) * s * sky.zenith.a * 1.6;
        }
    }

    // Sun: a hard disc, a stepped halo; moon: a pale crescent.
    let ds = dot(dir, sun);
    let disc = step(0.99955, ds);
    let halo = smoothstep(0.985, 0.9994, ds) * 0.35 + step(0.9975, ds) * 0.25;
    let sun_vis = smoothstep(-0.04, 0.02, sun.y);
    var bodies = (light * 14.0 + vec3<f32>(2.0)) * disc * sun_vis + light * halo * sun_vis * (0.5 + low);
    let dm = dot(dir, moon);
    let moon_disc = step(0.99965, dm);
    let bite = step(0.99965, dot(dir, normalize(moon + vec3<f32>(0.012, 0.006, 0.0))));
    let moon_vis = smoothstep(-0.02, 0.06, moon.y) * (0.35 + 0.65 * night);
    bodies = bodies + vec3<f32>(1.6, 1.65, 1.8) * moon_disc * (1.0 - bite * 0.85) * moon_vis + vec3<f32>(0.25, 0.3, 0.45) * smoothstep(0.996, 0.9996, dm) * moon_vis * 0.4;

    // Clouds on a plane overhead, drifting; a hard edge, lit and shaded tones.
    let cover = sky.horizon.a;
    var cloud = 0.0;
    var cloud_c = vec3<f32>(0.0);
    if (v > 0.0) {
        let drift = sky.cloud.xy + sky.cloud.zw * (globals.time - sky.time.x);
        let uv = dir.xz / (v + 0.12) * 0.9 + drift;
        let n = clouds_at(uv);
        let th = mix(0.78, 0.32, cover);
        let edge = smoothstep(th, th + 0.035, n) * smoothstep(0.0, 0.14, v);
        // Self-shadow: denser toward the light means this side faces away.
        let key = select(moon, sun, sun.y > -0.03);
        let n2 = clouds_at(uv + normalize(key.xz + vec2<f32>(1e-4, 0.0)) * 0.07);
        let shaded = step(n + 0.015, n2);
        let storm = sky.sun.w;
        let lit_c = mix(hor * 0.6 + light * 0.8, vec3<f32>(0.62, 0.64, 0.7) * (0.3 + 0.7 * length(light)), storm * 0.7);
        let shade_c = mix(mix(zen, hor, 0.5) * 0.75 + light * 0.12, vec3<f32>(0.32, 0.34, 0.4) * (0.25 + 0.6 * length(light)), storm * 0.8);
        cloud_c = mix(lit_c, shade_c, shaded);
        // A bright rim on edges facing the low sun.
        let rim = (1.0 - smoothstep(th + 0.01, th + 0.05, n)) * low * toward;
        cloud_c = cloud_c + light * rim * 0.6;
        cloud = edge;
    }
    c = mix(c + bodies, cloud_c, cloud);

    // Into the fog toward and below the horizon.
    c = mix(fog, c, smoothstep(-0.005, 0.07, v));
    // Lightning.
    c = c + vec3<f32>(0.7, 0.75, 0.9) * sky.fog.a * smoothstep(-0.1, 0.4, v);
    var out = vec4<f32>(c, 1.0);
@if(TONEMAP_IN_SHADER) {
    out = tone_mapping(out, view.color_grading);
}
    return out;
}
