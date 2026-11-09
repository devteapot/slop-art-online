// Full-screen finishing pass (after the main pass, on the displayed image), after Blue Protocol:
// - lines from depth and normal discontinuities, drawn on the far side of a silhouette so thin
//   or small things don't get thinner, fading with distance;
// - a rim of light on the side of silhouettes facing the sun (screen-space, from depth);
// - an anime "film" finish: a soft sky-coloured gradient from the top of the frame;
// - with the atmosphere (daylight.rs): fog banks lying in the low ground round you, drifting with
//   the wind (marched through the depth along each pixel's ray), and rain: streaks in three
//   layers at set distances, each drawn only where the scene lies beyond it.

import bevy_core_pipeline::fullscreen_vertex_shader::FullscreenVertexOutput;

@group(0) @binding(0) var screen_texture: texture_2d<f32>;
@group(0) @binding(1) var screen_sampler: sampler;
@group(0) @binding(2) var depth_texture: texture_depth_2d;
@group(0) @binding(3) var normal_texture: texture_2d<f32>;

struct Edges {
    // rgb: line colour (multiplies the scene), a: line strength.
    line: vec4<f32>,
    // x: depth threshold (relative), y: normal threshold (1 - cos), z: width (px), w: camera near.
    params: vec4<f32>,
    // x: fade start (m), y: fade end (m), z: rim width (px), w: rim strength.
    fade: vec4<f32>,
    // rgb: rim colour, a: unused.
    rim: vec4<f32>,
    // xy: sun direction on screen (unit, y down), zw: unused.
    sun: vec4<f32>,
    // rgb: gradient colour, a: gradient strength.
    grade: vec4<f32>,
    // xy: screen size (px), zw: 1 / size.
    screen: vec4<f32>,
    world_from_clip: mat4x4<f32>,
    // xyz: camera position, w: time (s).
    eye: vec4<f32>,
    // x: density, y: ground level, z: depth (m), w: march distance (m).
    bank: vec4<f32>,
    // rgb: colour, a: drift x.
    bank_color: vec4<f32>,
    // x: amount, y: slant, z: brightness, w: drift z.
    rain: vec4<f32>,
}

@group(0) @binding(4) var<uniform> edges: Edges;

// Distance from the camera (m) at a pixel; reverse-Z infinite perspective: depth = near / z.
fn dist(px: vec2<i32>) -> f32 {
    let size = vec2<i32>(edges.screen.xy);
    let p = clamp(px, vec2(0), size - vec2(1));
    let d = textureLoad(depth_texture, p, 0);
    return edges.params.w / max(d, 1e-7);
}

fn normal(px: vec2<i32>) -> vec3<f32> {
    let size = vec2<i32>(edges.screen.xy);
    let p = clamp(px, vec2(0), size - vec2(1));
    return textureLoad(normal_texture, p, 0).xyz * 2.0 - 1.0;
}

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

fn unproject(uv: vec2<f32>, depth: f32) -> vec3<f32> {
    let clip = vec4<f32>(uv.x * 2.0 - 1.0, 1.0 - uv.y * 2.0, depth, 1.0);
    let w = edges.world_from_clip * clip;
    return w.xyz / w.w;
}

// Fog banks: patches of mist in the low ground, thickest at the bottom of their layer.
fn bank_density(p: vec3<f32>) -> f32 {
    let drift = vec2<f32>(edges.bank_color.a, edges.rain.w);
    let q = p.xz - drift;
    let n = noise2(q / 46.0) * 0.65 + noise2(q / 17.0 + 5.0) * 0.35;
    let patches = smoothstep(0.48, 0.72, n);
    let h = p.y - edges.bank.y;
    let layer = 1.0 - smoothstep(-2.0, edges.bank.z, h);
    return patches * layer;
}

// Rain streaks of one layer: short slanted lines in cells, falling.
fn rain_layer(px: vec2<f32>, scale: f32, speed: f32, seed: f32) -> f32 {
    let t = edges.eye.w;
    var q = px / edges.screen.y * scale;
    q.x = q.x + q.y * edges.rain.y;
    let col = floor(q.x * 1.0);
    let r = hash2(vec2<f32>(col, seed));
    let y = q.y * 0.25 - t * speed - r * 7.0;
    let cell = floor(y);
    let r2 = hash2(vec2<f32>(col, cell + seed * 13.0));
    let fx = fract(q.x) - (0.2 + 0.6 * r2);
    let fy = fract(y);
    let line = (1.0 - smoothstep(0.0, 0.035, abs(fx))) * smoothstep(0.0, 0.15, fy) * (1.0 - smoothstep(0.25, 0.5, fy));
    return line * step(r2, edges.rain.x * 0.75 + 0.1);
}

@fragment
fn fragment(in: FullscreenVertexOutput) -> @location(0) vec4<f32> {
    var color = textureSample(screen_texture, screen_sampler, in.uv).rgb;
    let px = vec2<i32>(in.position.xy);
    let w = max(1, i32(round(edges.params.z)));
    let d0 = dist(px);
    let n0 = normal(px);
    let offsets = array<vec2<i32>, 4>(vec2(w, 0), vec2(-w, 0), vec2(0, w), vec2(0, -w));
    var edge = 0.0;
    var near_d = d0;
    for (var i = 0; i < 4; i++) {
        let q = px + offsets[i];
        let d = dist(q);
        // Depth: this pixel is behind a nearer neighbour (the line goes outside the silhouette).
        if ((d0 - d) / d > edges.params.x) {
            edge = 1.0;
            near_d = min(near_d, d);
        }
        // Normals: a crease, where depths are similar.
        if (abs(d0 - d) / d0 < edges.params.x && d0 < 1e6) {
            let c = 1.0 - dot(n0, normal(q));
            if (c > edges.params.y) {
                edge = max(edge, 0.7);
            }
        }
    }
    let fade = 1.0 - smoothstep(edges.fade.x, edges.fade.y, near_d);
    color = mix(color, color * edges.line.rgb, edge * edges.line.a * fade);

    // Rim: this pixel is near, and the pixel a little toward the sun is much farther (a
    // silhouette edge facing the light).
    let r = max(1.0, edges.fade.z);
    let toward = px + vec2<i32>(round(edges.sun.xy * r));
    let dt = dist(toward);
    if (d0 < 1e6 && (dt - d0) / d0 > 0.25) {
        let rf = 1.0 - smoothstep(edges.fade.x, edges.fade.y, d0);
        color = color + edges.rim.rgb * edges.fade.w * rf;
    }

    // Fog banks: march from the camera to what this pixel sees (or the march distance).
    let raw_depth = textureLoad(depth_texture, clamp(px, vec2(0), vec2<i32>(edges.screen.xy) - vec2(1)), 0);
    if (edges.bank.x > 0.005) {
        let eye = edges.eye.xyz;
        let far_p = unproject(in.uv, max(raw_depth, 1e-6));
        let to = far_p - eye;
        let len = min(length(to), edges.bank.w);
        let dir = normalize(unproject(in.uv, 0.5) - eye);
        let steps = 6;
        let jitter = hash2(in.position.xy + fract(edges.eye.w) * 17.0);
        var acc = 0.0;
        for (var i = 0; i < steps; i++) {
            let s = (f32(i) + jitter) / f32(steps) * len;
            acc = acc + bank_density(eye + dir * s);
        }
        let thick = acc / f32(steps) * len * 0.045 * edges.bank.x;
        let a = (1.0 - exp(-thick)) * 0.85;
        color = mix(color, edges.bank_color.rgb, a);
    }

    // Rain: four layers at set distances, near ones larger, faster and brighter, far ones finer
    // and fainter (the falloff gives the air depth); each stops at nearer things. Heavy rain
    // (a storm, above 1) brings the farther layers in more strongly.
    if (edges.rain.x > 0.005) {
        let p = in.position.xy;
        let d = d0;
        let heavy = clamp(edges.rain.x - 0.85, 0.0, 0.5) * 2.0;
        var rain = 0.0;
        rain = rain + rain_layer(p, 45.0, 2.3, 1.0) * smoothstep(1.5, 3.0, d);
        rain = rain + rain_layer(p + vec2<f32>(37.0, 11.0), 80.0, 3.3, 2.0) * smoothstep(5.0, 8.0, d) * 0.7;
        rain = rain + rain_layer(p + vec2<f32>(71.0, 53.0), 140.0, 4.5, 3.0) * smoothstep(12.0, 18.0, d) * (0.42 + 0.15 * heavy);
        rain = rain + rain_layer(p + vec2<f32>(13.0, 91.0), 230.0, 5.8, 4.0) * smoothstep(26.0, 36.0, d) * (0.18 + 0.2 * heavy);
        color = color + vec3<f32>(0.78, 0.85, 0.96) * rain * edges.rain.z * min(edges.rain.x, 1.0);
        // The air greys a little.
        color = mix(color, vec3<f32>(dot(color, vec3<f32>(0.3, 0.5, 0.2))), 0.06 * min(edges.rain.x, 1.0));
    }

    // Film finish: a soft gradient from the top (screen blend).
    let g = edges.grade.rgb * edges.grade.a * pow(1.0 - in.uv.y, 2.0);
    color = 1.0 - (1.0 - color) * (1.0 - g);
    return vec4<f32>(color, 1.0);
}
