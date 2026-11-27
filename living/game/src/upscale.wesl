// The scaled 3D picture drawn onto the native-resolution output (`graphics.rs`, only when the 3D
// render scale is below 100%): Catmull-Rom (bicubic) resampling, contrast-adaptive sharpening
// (after AMD's CAS) and an anti-ringing clamp, so ink outlines, eyes and hair lines keep their snap
// through a non-integer stretch (1.36x at Auto on a 2x display) where plain bilinear smeared them,
// without crushing or tinting the ink or haloing the ground beside it (look-dev 4c).
// - Perceptual space: every texel is filtered as sqrt(linear) (gamma 2) and squared back at the
//   end. In linear light the warm-brown ink is ~0.01-0.02 against 0.3-0.6 stone, so 4b's linear
//   filter pushed it below zero: black ink at noon, red ink at night.
// - Catmull-Rom from the 2x2 nearest texels (three gathers, weighted exactly in gamma 2) plus four
//   bilinear taps for the outer ring (the corner taps of the 4x4 kernel dropped; their weights are
//   tiny), after Jorge Jimenez's filmic SMAA sharp filter.
// - CAS: the four bilinear neighbours one source texel away pull the centre apart from their mean,
//   less where the cross already spans most of the range.
// - Anti-ringing: the result is clamped to the min and max of the 2x2 nearest texels, so an
//   outline is never darker than its ink nor the stone beside it brighter than the stone. The
//   sharpening therefore only steepens edges inside that range, which is why the default runs
//   CAS at full strength (`Upscale::SHARPNESS`); clamping before CAS instead (variant 1) rings again.
// The source is sRGB: taps and gathers come back linear, and the output target encodes again.

import bevy_ui_render::ui_vertex_output::UiVertexOutput;

struct Upscale {
    // x: CAS sharpness (0 none .. 1 most), y: 1 filtered, 0 plain bilinear (A/B only),
    // z: 2 Catmull-Rom then CAS then clamp (the default), 0 clamped Catmull-Rom, 1 clamped
    // Catmull-Rom then CAS (both A/B only).
    params: vec4<f32>,
}

@group(1) @binding(0) var<uniform> upscale: Upscale;
@group(1) @binding(1) var source: texture_2d<f32>;
@group(1) @binding(2) var source_sampler: sampler;

fn tap(uv: vec2<f32>) -> vec3<f32> {
    return textureSampleLevel(source, source_sampler, uv, 0.0).rgb;
}

// A bilinear tap in gamma 2.
fn tap2(uv: vec2<f32>) -> vec3<f32> {
    return sqrt(max(tap(uv), vec3<f32>(0.0)));
}

@fragment
fn fragment(in: UiVertexOutput) -> @location(0) vec4<f32> {
    let uv = in.uv;
    if (upscale.params.y < 0.5) {
        return vec4<f32>(tap(uv), 1.0);
    }
    let size = vec2<f32>(textureDimensions(source));
    let inv = 1.0 / size;

    // Catmull-Rom weights; t1 is the centre of the top-left texel of the nearest 2x2.
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

    // The 2x2 nearest texels, exactly, in gamma 2. Gather order: x (0,1), y (1,1), z (1,0), w (0,0).
    let corner = (t1 + 0.5) * inv;
    let gr = sqrt(max(textureGather(0, source, source_sampler, corner), vec4<f32>(0.0)));
    let gg = sqrt(max(textureGather(1, source, source_sampler, corner), vec4<f32>(0.0)));
    let gb = sqrt(max(textureGather(2, source, source_sampler, corner), vec4<f32>(0.0)));
    let q00 = vec3<f32>(gr.w, gg.w, gb.w);
    let q10 = vec3<f32>(gr.z, gg.z, gb.z);
    let q01 = vec3<f32>(gr.x, gg.x, gb.x);
    let q11 = vec3<f32>(gr.y, gg.y, gb.y);
    let lo4 = min(min(q00, q10), min(q01, q11));
    let hi4 = max(max(q00, q10), max(q01, q11));

    let ka = w12.x * w0.y;
    let kb = w0.x * w12.y;
    let kc = w12.x * w12.y;
    let kd = w3.x * w12.y;
    let ke = w12.x * w3.y;
    let centre = q00 * (w1.x * w1.y) + q10 * (w2.x * w1.y) + q01 * (w1.x * w2.y) + q11 * (w2.x * w2.y);
    var c = tap2(vec2<f32>(t12.x, t0.y)) * ka + tap2(vec2<f32>(t0.x, t12.y)) * kb + centre
        + tap2(vec2<f32>(t3.x, t12.y)) * kd + tap2(vec2<f32>(t12.x, t3.y)) * ke;
    c = c / (ka + kb + kc + kd + ke);

    let variant = upscale.params.z;
    if (variant < 0.5) {
        let o = clamp(c, lo4, hi4);
        return vec4<f32>(o * o, 1.0);
    }
    if (variant < 1.5) {
        c = clamp(c, lo4, hi4);
    }

    // Contrast-adaptive sharpening, in gamma 2.
    let n = tap2(uv + vec2<f32>(0.0, -inv.y));
    let s = tap2(uv + vec2<f32>(0.0, inv.y));
    let w = tap2(uv + vec2<f32>(-inv.x, 0.0));
    let e = tap2(uv + vec2<f32>(inv.x, 0.0));
    let lo = min(c, min(min(n, s), min(w, e)));
    let hi = max(c, max(max(n, s), max(w, e)));
    let amp = sqrt(clamp(min(lo, 1.0 - hi) / max(hi, vec3<f32>(1e-4)), vec3<f32>(0.0), vec3<f32>(1.0)));
    let k = amp * (-1.0 / mix(8.0, 5.0, clamp(upscale.params.x, 0.0, 1.0)));
    var o = (c + (n + s + w + e) * k) / (1.0 + 4.0 * k);
    if (variant < 1.5) {
        o = clamp(o, vec3<f32>(0.0), vec3<f32>(1.0));
    } else {
        o = clamp(o, lo4, hi4);
    }
    return vec4<f32>(o * o, 1.0);
}
