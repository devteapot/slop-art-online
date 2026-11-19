// The session recorder's small copy of the finished frame (record_frames.rs), box-filtered so
// a 3–5× reduction averages the pixels it covers instead of picking one. A view composited in sRGB is converted to linear light first,
// as Bevy's own blit does, so the copy has the screen's colours.
import bevy_core_pipeline::fullscreen_vertex_shader::FullscreenVertexOutput;
@if(SRGB_TO_LINEAR) import bevy_render::color_operations::srgb_to_linear;

@group(0) @binding(0) var screen: texture_2d<f32>;
@group(0) @binding(1) var screen_sampler: sampler;

@fragment
fn fragment(in: FullscreenVertexOutput) -> @location(0) vec4<f32> {
    // A 4×4 grid of bilinear taps across this destination texel: each tap averages 2×2 source
    // texels, so a reduction up to about 8× is box-filtered (dithered fades do not alias).
    let texel = fwidth(in.uv);
    var c = vec3(0.0);
    for (var j = 0; j < 4; j++) {
        for (var i = 0; i < 4; i++) {
            let o = (vec2(f32(i), f32(j)) + 0.5) / 4.0 - 0.5;
            c += textureSampleLevel(screen, screen_sampler, in.uv + o * texel, 0.0).rgb;
        }
    }
    var rgb = c / 16.0;
    @if(SRGB_TO_LINEAR)
    rgb = srgb_to_linear(rgb);
    return vec4(rgb, 1.0);
}
