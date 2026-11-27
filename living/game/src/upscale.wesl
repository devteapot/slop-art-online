// The scaled 3D picture drawn onto the native-resolution output (`graphics.rs`, only when the 3D
// render scale is below 100%): Catmull-Rom (bicubic) resampling, then a light contrast-adaptive
// sharpen (after AMD's CAS), so ink outlines, eyes and hair lines keep their snap through a
// non-integer stretch (1.36x at Auto on a 2x display) where plain bilinear smeared them.
// - Catmull-Rom from five bilinear taps (the corner taps of the 4x4 kernel dropped; their weights
//   are tiny), after Jorge Jimenez's filmic SMAA sharp filter.
// - CAS: the four bilinear neighbours one source texel away pull the centre apart from their
//   mean, less where the cross already spans most of the range (no clipping, no halos on ink).
// The source is sRGB: taps come back linear, and the output target encodes again.

import bevy_ui_render::ui_vertex_output::UiVertexOutput;

struct Upscale {
    // x: CAS sharpness (0 none .. 1 most), y: 1 Catmull-Rom + CAS, 0 plain bilinear (A/B only).
    params: vec4<f32>,
}

@group(1) @binding(0) var<uniform> upscale: Upscale;
@group(1) @binding(1) var source: texture_2d<f32>;
@group(1) @binding(2) var source_sampler: sampler;

fn tap(uv: vec2<f32>) -> vec3<f32> {
    return textureSampleLevel(source, source_sampler, uv, 0.0).rgb;
}

@fragment
fn fragment(in: UiVertexOutput) -> @location(0) vec4<f32> {
    let uv = in.uv;
    if (upscale.params.y < 0.5) {
        return vec4<f32>(tap(uv), 1.0);
    }
    let size = vec2<f32>(textureDimensions(source));
    let inv = 1.0 / size;

    // Catmull-Rom.
    let p = uv * size;
    let t1 = floor(p - 0.5) + 0.5;
    let f = p - t1;
    let w0 = f * (-0.5 + f * (1.0 - 0.5 * f));
    let w1 = 1.0 + f * f * (-2.5 + 1.5 * f);
    let w2 = f * (0.5 + f * (2.0 - 1.5 * f));
    let w3 = f * f * (-0.5 + 0.5 * f);
    let w12 = w1 + w2;
    let t0 = (t1 - 1.0) * inv;
    let t3 = (t1 + 2.0) * inv;
    let t12 = (t1 + w2 / w12) * inv;
    let ka = w12.x * w0.y;
    let kb = w0.x * w12.y;
    let kc = w12.x * w12.y;
    let kd = w3.x * w12.y;
    let ke = w12.x * w3.y;
    var c = tap(vec2<f32>(t12.x, t0.y)) * ka + tap(vec2<f32>(t0.x, t12.y)) * kb + tap(t12) * kc
        + tap(vec2<f32>(t3.x, t12.y)) * kd + tap(vec2<f32>(t12.x, t3.y)) * ke;
    c = c / (ka + kb + kc + kd + ke);

    // Contrast-adaptive sharpening.
    let n = tap(uv + vec2<f32>(0.0, -inv.y));
    let s = tap(uv + vec2<f32>(0.0, inv.y));
    let w = tap(uv + vec2<f32>(-inv.x, 0.0));
    let e = tap(uv + vec2<f32>(inv.x, 0.0));
    let lo = min(c, min(min(n, s), min(w, e)));
    let hi = max(c, max(max(n, s), max(w, e)));
    let amp = sqrt(clamp(min(lo, 1.0 - hi) / max(hi, vec3<f32>(1e-4)), vec3<f32>(0.0), vec3<f32>(1.0)));
    let k = amp * (-1.0 / mix(8.0, 5.0, clamp(upscale.params.x, 0.0, 1.0)));
    let sharp = (c + (n + s + w + e) * k) / (1.0 + 4.0 * k);
    return vec4<f32>(clamp(sharp, vec3<f32>(0.0), vec3<f32>(1.0)), 1.0);
}
