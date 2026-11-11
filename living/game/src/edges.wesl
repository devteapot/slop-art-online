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
    // xy: sun direction on screen (unit, y down), z: the smallest step a crease line marks (m;
    // 0 marks every crease), w: unused.
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
    // xy: where my character stands (world x, z), z: sight radius (m), w: mode (0 none,
    // 1 not seen now, 2 limited view).
    sight: vec4<f32>,
    // x, y: soft band inside and beyond the radius (m), z: dimming, w: desaturation.
    sight_look: vec4<f32>,
    // rgb: fog colour (linear), a: flattening toward it (not seen now).
    sight_fog: vec4<f32>,
    // x: fully fogged at this multiple of the radius (limited view), y: how far what lies
    // behind something fogs (limited view).
    sight_far: vec4<f32>,
    // The sight field (sightfield.rs): xy the world x, z of its corner, z one over its size in
    // metres, w 1 when it holds a field.
    sight_field: vec4<f32>,
    // x: how not seen now is drawn (sightedge::Look: 0 grey, 1 wash, 2 lantern, 3 shadows,
    // 4 hatch, 5 memory), y: how light the scene is (0 night, 1 day), z: 1 when the memory
    // texture is current.
    sight_extra: vec4<f32>,
}

@group(0) @binding(4) var<uniform> edges: Edges;
// Where my sight lines reach: 1 seen, 0 behind something (two texels a tile, filtered).
@group(0) @binding(5) var field_texture: texture_2d<f32>;
@group(0) @binding(6) var field_sampler: sampler;
// How recently each texel was seen (the memory look): 1 now, 0 long ago or never.
@group(0) @binding(7) var memory_texture: texture_2d<f32>;

// How far a ground point (world x, z) lies behind something my sight lines don't pass: 0 seen,
// 1 hidden; 0 outside the field (the radius covers that). The filtered texels give a soft edge
// of about half a tile; the smoothstep keeps its middle where the authority's test flips.
fn behind(xz: vec2<f32>) -> f32 {
    if (edges.sight_field.w < 0.5) {
        return 0.0;
    }
    let uv = (xz - edges.sight_field.xy) * edges.sight_field.z;
    if (any(uv < vec2<f32>(0.0)) || any(uv > vec2<f32>(1.0))) {
        return 0.0;
    }
    let seen = textureSampleLevel(field_texture, field_sampler, uv, 0.0).r;
    return 1.0 - smoothstep(0.2, 0.8, seen);
}

// How recently a ground point was seen (memory look): 1 now, 0 long ago, never, or outside.
fn remembered(xz: vec2<f32>) -> f32 {
    if (edges.sight_extra.z < 0.5 || edges.sight_field.w < 0.5) {
        return 0.0;
    }
    let uv = (xz - edges.sight_field.xy) * edges.sight_field.z;
    if (any(uv < vec2<f32>(0.0)) || any(uv > vec2<f32>(1.0))) {
        return 0.0;
    }
    return textureSampleLevel(memory_texture, field_sampler, uv, 0.0).r;
}

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

// The world point at a pixel.
fn world_at(px: vec2<i32>) -> vec3<f32> {
    let size = vec2<i32>(edges.screen.xy);
    let p = clamp(px, vec2(0), size - vec2(1));
    let d = textureLoad(depth_texture, p, 0);
    return unproject((vec2<f32>(p) + 0.5) * edges.screen.zw, max(d, 1e-7));
}

// Walking from `start` along `dir` for a few samples: the first face parallel to the one at `a`
// (normal `na`) lies within `sun.z` metres of its plane.
fn small_step(a: vec2<i32>, na: vec3<f32>, start: vec2<i32>, dir: vec2<i32>) -> bool {
    let pa = world_at(a);
    for (var k = 0; k < 6; k++) {
        let s = start + dir * k;
        if (1.0 - dot(na, normal(s)) < edges.params.y * 0.5) {
            return abs(dot(na, world_at(s) - pa)) < edges.sun.z;
        }
    }
    return false;
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

fn luma(c: vec3<f32>) -> f32 {
    return dot(c, vec3<f32>(0.2126, 0.7152, 0.0722));
}

fn fbm(p: vec2<f32>) -> f32 {
    return noise2(p) * 0.5 + noise2(p * 2.03 + 7.1) * 0.3 + noise2(p * 4.1 + 3.7) * 0.2;
}

// The paper the looks draw on: warm by day, a dark blue-grey at night (light 0 night, 1 day).
fn paper(light: f32) -> vec3<f32> {
    return mix(vec3<f32>(0.030, 0.034, 0.055), vec3<f32>(0.78, 0.71, 0.56), light);
}

// Wash: a faded watercolour over what isn't seen: its hues kept faintly and its values softened
// toward warm paper, in long slanted brush strokes; the edge is a dry brush, with pigment pooling
// darker along it.
fn look_wash(color: vec3<f32>, p: vec3<f32>, t0: f32, light: f32) -> vec3<f32> {
    let q = vec2<f32>(p.x * 0.8 + p.z * 0.6, -p.x * 0.6 + p.z * 0.8);
    let n = fbm(q * vec2<f32>(0.9, 3.5));
    let ragged = t0 + (n - 0.5) * 0.8;
    let t = smoothstep(0.42, 0.58, ragged);
    if (t <= 0.0) {
        return color;
    }
    let pap = paper(light);
    let l = luma(color);
    let hue = mix(vec3<f32>(l), color, 0.4);
    var g = mix(hue, pap * (0.6 + 0.4 * clamp(l / max(luma(pap), 1e-3), 0.0, 1.5)), 0.55);
    // Strokes: the wash laid on in bands, a little uneven.
    let stroke = fbm(q * vec2<f32>(0.35, 2.6) + 11.0);
    g = g * (0.86 + 0.26 * stroke) * (0.96 + 0.08 * noise2(p.xz * 7.0));
    let pool = smoothstep(0.5, 0.58, ragged) * (1.0 - smoothstep(0.58, 0.9, ragged));
    g = g * (1.0 - 0.4 * pool);
    return mix(color, g, t);
}

// Lantern: my sight as light. A pool round me that falls off toward the radius, a wide
// penumbra behind what blocks (the field taken over five points 0.9 m apart), darkness beyond
// (cooler and greyer, lighter by day), and a warm rim where the light ends.
fn look_lantern(color: vec3<f32>, p: vec3<f32>, reach: f32, r: f32, sky: f32, light: f32) -> vec3<f32> {
    let s = 1.4;
    let h = (behind(p.xz) * 2.0 + behind(p.xz + vec2<f32>(s, 0.0)) + behind(p.xz - vec2<f32>(s, 0.0)) + behind(p.xz + vec2<f32>(0.0, s)) + behind(p.xz - vec2<f32>(0.0, s))) / 6.0;
    let pool = 1.0 - smoothstep(r - 7.0, r + 2.0, reach);
    let lit = mix(1.0, pool * (1.0 - h), sky);
    let dark = mix(0.06, 0.24, light);
    let l = luma(color);
    let night = mix(vec3<f32>(l), color, 0.3) * vec3<f32>(0.62, 0.78, 1.25) * dark;
    let rim = smoothstep(0.1, 0.5, lit) * (1.0 - smoothstep(0.5, 0.9, lit));
    let warm = color * (vec3<f32>(1.0) + rim * vec3<f32>(0.55, 0.28, 0.0));
    return mix(night, warm, smoothstep(0.0, 1.0, lit));
}

// Shadows: sight shadows cast from my eye by what blocks it, in the toon shadow's way (hue
// shifted toward blue-violet, saturation kept): sharp by the blocker, the penumbra widening with
// distance from me (the field taken across the shadow's direction). Beyond my sight the light
// has fallen off: the same shadow.
fn look_shadows(color: vec3<f32>, p: vec3<f32>, reach: f32, r: f32, sky: f32, light: f32) -> vec3<f32> {
    let d = p.xz - edges.sight.xy;
    let dl = max(length(d), 1e-3);
    let across = vec2<f32>(-d.y, d.x) / dl;
    let w = 0.1 + 0.045 * dl;
    var h = 0.0;
    for (var i = 0; i < 5; i++) {
        let o = (f32(i) - 2.0) * 0.5 * w;
        h = h + behind(p.xz + across * o);
    }
    h = smoothstep(0.4, 0.6, h / 5.0);
    let s = max(h, smoothstep(r - 1.5, r + 4.0, reach)) * sky;
    // Half the colour kept, half its value in the shadow hue, dimmer (darker at night).
    let l = luma(color);
    let tint = vec3<f32>(0.40, 0.42, 0.72) * l * 1.5;
    let shade = mix(color, tint, 0.55) * mix(0.42, 0.6, light);
    return mix(color, shade, s);
}

// A pencil line every unit of x, fading to its average where it would be finer than a pixel
// (`px`: the period's size in pixels).
fn hatch_line(x: f32, px: f32) -> f32 {
    let f = abs(fract(x) - 0.5);
    let soft = 1.0 / max(px, 1.0);
    let line = 1.0 - smoothstep(0.13, 0.13 + soft, 0.5 - f);
    return mix(line, 0.26, 1.0 - smoothstep(2.5, 5.0, px));
}

// Hatch: what isn't seen is paper with pencil hatching, denser where the scene is darker
// (one, two, then three directions), on the surface's own plane; the strokes come in ragged at
// the edge before the paper does. By night the paper is dark and the strokes are chalk.
fn look_hatch(color: vec3<f32>, p: vec3<f32>, n: vec3<f32>, t0: f32, d0: f32, light: f32) -> vec3<f32> {
    let t = clamp(t0 + (noise2(p.xz * 1.3) - 0.5) * 0.5, 0.0, 1.0);
    if (t <= 0.001) {
        return color;
    }
    var uv = p.xz;
    let an = abs(n);
    if (an.y < 0.6) {
        if (an.x > an.z) {
            uv = p.zy;
        } else {
            uv = p.xy;
        }
    }
    let pap = paper(light) * vec3<f32>(0.92, 0.86, 0.74);
    let tone = clamp(luma(color) / max(luma(pap) * 1.15, 1e-3), 0.0, 1.0);
    let spacing = 0.16;
    // The period's size on screen (px), from the distance and how much the surface faces me.
    let view = normalize(edges.eye.xyz - p);
    let px = spacing / max(d0 * edges.screen.w * 0.9 / max(abs(dot(n, view)), 0.25), 1e-4);
    let wob = noise2(uv * 2.5) * 0.35;
    let h1 = hatch_line(dot(uv, vec2<f32>(0.7071, 0.7071)) / spacing + wob, px);
    let h2 = hatch_line(dot(uv, vec2<f32>(0.7071, -0.7071)) / spacing + wob * 1.3, px);
    let h3 = hatch_line(uv.x / (spacing * 0.8) + wob, px * 0.8);
    var ink = h1 * (1.0 - smoothstep(0.85, 1.0, tone)) * smoothstep(0.1, 0.4, t);
    ink = max(ink, h2 * (1.0 - smoothstep(0.5, 0.7, tone)) * smoothstep(0.3, 0.6, t));
    ink = max(ink, h3 * (1.0 - smoothstep(0.2, 0.4, tone)) * smoothstep(0.5, 0.8, t));
    let lead = mix(pap * 2.6 + vec3<f32>(0.05), pap * vec3<f32>(0.42, 0.30, 0.22), light);
    var g = mix(pap * (0.85 + 0.15 * tone), color, 0.1);
    g = g * (0.95 + 0.1 * noise2(p.xz * 9.0));
    let washed = mix(color, g, smoothstep(0.45, 0.8, t));
    return mix(washed, lead, ink * 0.8);
}

// Memory: ground seen now is in colour; ground seen recently keeps its colour and drains of it as
// the memory fades (remembered()); ground not seen for a while, or never, is a pencil sketch on
// paper (its lines and a hint of its values).
fn look_memory(color: vec3<f32>, p: vec3<f32>, t0: f32, ground: f32, line: f32, light: f32) -> vec3<f32> {
    let c = max(1.0 - t0, remembered(p.xz) * ground);
    if (c >= 0.999) {
        return color;
    }
    let pap = mix(paper(light), vec3<f32>(luma(paper(light))) * 1.08, 0.7) * mix(0.6, 1.0, light);
    let l = luma(color);
    var sk = pap * (0.8 + 0.2 * clamp(l / max(luma(pap), 1e-3), 0.0, 1.2));
    sk = mix(sk, sk * mix(2.2, 0.4, light), line);
    let drained = mix(vec3<f32>(l), color, smoothstep(0.35, 1.0, c));
    return mix(sk, drained, smoothstep(0.0, 0.55, c));
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
        // Normals: a crease, where depths are similar. Both faces must go on for another sample
        // (mine behind me, theirs beyond them): a face a pixel or so wide, such as a slate's
        // lower edge or a sill seen from afar, comes and goes between pixels as the view moves,
        // and its lines beaded and crawled along every row of a roof (the owner's Cullet walk).
        if (abs(d0 - d) / d0 < edges.params.x && d0 < 1e6) {
            let nq = normal(q);
            let c = 1.0 - dot(n0, nq);
            if (c > edges.params.y) {
                // Not a step smaller than `sun.z` between two parallel faces (a slate's lower
                // edge, a sill): either the face past my neighbour is parallel to mine and near my
                // plane, or I am the step and the face behind me is parallel to my neighbour's.
                // World-sized, so the same at every distance.
                let o = offsets[i];
                let small = edges.sun.z > 0.0 && (small_step(px, n0, q + o, o) || small_step(q, nq, px - o, -o));
                if (!small) {
                    edge = max(edge, 0.7);
                }
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

    let raw_depth = textureLoad(depth_texture, clamp(px, vec2(0), vec2<i32>(edges.screen.xy) - vec2(1)), 0);

    // The edge of my character's sight (sightedge.rs): a radius round me on the ground plane,
    // and what my sight lines don't reach within it (the sight field).
    // Not seen now: there, dimmer, greyer, flatter and a little cooler (the sky is left alone).
    // Limited view: beyond the radius, into the fog's colour by sight_far × the radius, and
    // behind things most of the way; nothing is drawn past that, so the sky and what was not
    // drawn are fog too.
    if (edges.sight.w > 0.5) {
        var reach = 1e9;
        var hid = 0.0;
        var p = vec3<f32>(0.0);
        if (raw_depth > 1e-7) {
            p = unproject(in.uv, raw_depth);
            reach = length(p.xz - edges.sight.xy);
            hid = behind(p.xz);
        }
        let r = edges.sight.z;
        let look = i32(round(edges.sight_extra.x));
        let ground = step(1e-7, raw_depth);
        let t0 = max(smoothstep(r - edges.sight_look.x, r + edges.sight_look.y, reach), hid) * ground;
        let light = edges.sight_extra.y;
        if (edges.sight.w < 1.5 && look == 1) {
            color = look_wash(color, p, t0, light);
        } else if (edges.sight.w < 1.5 && look == 2) {
            color = look_lantern(color, p, reach, r, ground, light);
        } else if (edges.sight.w < 1.5 && look == 3) {
            color = look_shadows(color, p, reach, r, ground, light);
        } else if (edges.sight.w < 1.5 && look == 4) {
            color = look_hatch(color, p, n0, t0, d0, light);
        } else if (edges.sight.w < 1.5 && look == 5) {
            color = look_memory(color, p, t0, ground, edge * edges.line.a * fade, light);
        } else if (edges.sight.w < 1.5) {
            let t = max(smoothstep(r - edges.sight_look.x, r + edges.sight_look.y, reach), hid) * step(1e-7, raw_depth);
            let l = dot(color, vec3<f32>(0.2126, 0.7152, 0.0722));
            // Greyer; flatter toward the fog's colour (it follows the light, so night stays
            // dark); dimmer and a little cooler.
            var g = mix(color, vec3<f32>(l), edges.sight_look.w);
            g = mix(g, edges.sight_fog.rgb, edges.sight_fog.a);
            g = g * (1.0 - edges.sight_look.z) * vec3<f32>(0.95, 0.98, 1.05);
            color = mix(color, g, t);
        } else {
            let t = max(smoothstep(r, r * edges.sight_far.x, reach), hid * edges.sight_far.y);
            color = mix(color, edges.sight_fog.rgb, t);
        }
    }

    // Fog banks: march from the camera to what this pixel sees (or the march distance).
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
