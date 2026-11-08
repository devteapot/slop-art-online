// Full-screen finishing pass (after the main pass, on the displayed image), after Blue Protocol:
// - lines from depth and normal discontinuities, drawn on the far side of a silhouette so thin
//   or small things don't get thinner, fading with distance;
// - a rim of light on the side of silhouettes facing the sun (screen-space, from depth);
// - an anime "film" finish: a soft sky-coloured gradient from the top of the frame.

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

    // Film finish: a soft gradient from the top (screen blend).
    let g = edges.grade.rgb * edges.grade.a * pow(1.0 - in.uv.y, 2.0);
    color = 1.0 - (1.0 - color) * (1.0 - g);
    return vec4<f32>(color, 1.0);
}
