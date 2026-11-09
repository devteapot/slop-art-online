// Toon water (water.rs): banded depth colour from the depth prepass, a foam line at shores and
// lines washing toward them, thin animated highlight bands, a stylised reflection of the sky's
// gradient with a stepped glint of the key light, and rings when it rains. Fogged like the land.

import bevy_pbr::render::{
    forward_io::VertexOutput,
    mesh_view_bindings as vb,
    mesh_view_types,
};
@if(DEPTH_PREPASS) import bevy_pbr::prepass::utils::prepass_depth;
@if(TONEMAP_IN_SHADER) import bevy_core_pipeline::tonemapping::tone_mapping;

struct Water {
    shallow: vec4<f32>,
    deep: vec4<f32>,
    foam: vec4<f32>,
    zenith: vec4<f32>,
    horizon: vec4<f32>,
    extra: vec4<f32>,
}

@group(constants::MATERIAL_BIND_GROUP) @binding(0)
var<uniform> water: Water;

fn hash2(p: vec2<f32>) -> f32 {
    var q = fract(p * vec2<f32>(123.34, 456.21));
    q = q + dot(q, q + 45.32);
    return fract(q.x * q.y);
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

@fragment
fn fragment(in: VertexOutput) -> @location(0) vec4<f32> {
    let p = in.world_position.xyz;
    let eye = vb::view.world_position.xyz;
    let V = normalize(eye - p);
    let t = vb::globals.time;
    let wind = water.horizon.a;

    // Depth below the surface: the scene behind it (depth prepass) less the surface, in view
    // distance (reverse-Z infinite projection: depth = near / z), turned toward vertical.
    var depth = 6.0;
@if(DEPTH_PREPASS) {
    let near = vb::view.clip_from_view[3][2];
    let surf = near / max(in.position.z, 1e-7);
    let behind = near / max(prepass_depth(in.position, 0u), 1e-7);
    depth = clamp(behind - surf, 0.0, 60.0) * max(V.y, 0.3);
}

    // Gentle motion: two noise layers drifting with the wind.
    let q = p.xz;
    let flow = vec2<f32>(0.94, 0.34) * t * (0.3 + 0.6 * wind);
    let n1 = noise2(q * 0.09 + flow * 0.05);
    let n2 = noise2(q * 0.27 - flow * 0.11 + vec2<f32>(4.0, 1.0));
    let n = n1 * 0.65 + n2 * 0.35;
    let N = normalize(vec3<f32>((n1 - 0.5) * (0.18 + 0.2 * wind), 1.0, (n2 - 0.5) * (0.18 + 0.2 * wind)));

    // Colour by depth, in soft bands.
    let deep_t = 1.0 - exp(-depth / water.deep.a);
    let stepped = floor(deep_t * 3.0 + n * 0.6) / 3.0;
    let base = mix(water.shallow.rgb, water.deep.rgb, clamp(mix(deep_t, stepped, 0.55), 0.0, 1.0));

    // The key light (as the toon shader: Lambert's 1/π at the camera's exposure) and the sky's fill.
    var sun = vec3<f32>(1.0);
    var L = vec3<f32>(0.0, 1.0, 0.0);
    if (vb::lights.n_directional_lights > 0u) {
        let l = &vb::lights.directional_lights[0];
        L = (*l).direction_to_light;
        sun = (*l).color.rgb * vb::view.exposure / 3.14159265 * 0.82;
    }
    let amb = vb::lights.ambient_color;
    let fill = select(vec3<f32>(0.0), amb.rgb, amb.a > 0.0);
    var col = base * sun * (0.6 + 0.4 * max(dot(N, L), 0.0)) + base * fill * 1.5;

    // Reflection of the sky's gradient, stronger at grazing angles, and a stepped glint.
    let R = reflect(-V, N);
    let sky = mix(water.horizon.rgb, water.zenith.rgb, smoothstep(0.0, 0.6, R.y));
    let fres = 0.1 + 0.6 * pow(1.0 - max(V.y, 0.0), 4.0);
    col = mix(col, sky, fres);
    let g = dot(R, L);
    let sun_level = min(length(sun), 1.6);
    col = col + sun * (step(0.994, g) * 0.8 + step(0.978, g) * 0.12) * (0.5 + 0.5 * n);

    // Thin highlight bands where the waves crest.
    let band = smoothstep(0.585, 0.6, n) * (1.0 - smoothstep(0.615, 0.63, n));
    col = mix(col, sky * 0.6 + vec3<f32>(0.45) * sun_level, band * 0.35);

    // Foam: a line along the shore, and lines washing in.
    let fw = water.foam.a;
    let shore = 1.0 - smoothstep(fw * 0.45, fw, depth + (n2 - 0.5) * 0.18);
    let wash = step(0.82, fract(depth * 2.0 - t * 0.3 + n1 * 0.8)) * (1.0 - smoothstep(fw, fw * 3.2, depth));
    let foam = max(shore, wash * 0.65);
    col = mix(col, water.foam.rgb * (sun_level * 0.6 + fill * 2.0 + 0.04), foam);

    // Rain: rings opening on the surface.
    let rain = water.zenith.a;
    if (rain > 0.01) {
        let rq = q * 0.9;
        let cell = floor(rq);
        let f = fract(rq) - 0.5;
        let h = hash2(cell);
        let ph = fract(t * 0.9 + h * 7.0);
        let c0 = (vec2<f32>(hash2(cell + 1.3), hash2(cell + 2.7)) - 0.5) * 0.5;
        let r = length(f - c0);
        let ring = (1.0 - smoothstep(0.0, 0.035, abs(r - ph * 0.42))) * (1.0 - ph) * step(h, rain * 0.85);
        col = col + vec3<f32>(0.6, 0.65, 0.7) * ring * (sun_level * 0.35 + 0.05);
    }

    var alpha = mix(0.45, water.shallow.a, deep_t);
    alpha = max(max(alpha, foam), fres * 0.8);

@if(DISTANCE_FOG) {
    let fog = vb::fog;
    if (fog.mode == mesh_view_types::FOG_MODE_LINEAR) {
        let dist = length(p - eye);
        let a = fog.base_color.a * (1.0 - clamp((fog.be.y - dist) / (fog.be.y - fog.be.x), 0.0, 1.0));
        col = mix(col, fog.base_color.rgb, a);
        alpha = mix(alpha, 1.0, a);
    }
}
    var out = vec4<f32>(col, alpha);
@if(TONEMAP_IN_SHADER) {
    out = tone_mapping(out, vb::view.color_grading);
}
    return out;
}
