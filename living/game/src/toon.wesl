// One shading model for everything (docs/GAME_BRIEF.md, "Art direction"): the sun's light in
// two bands with a soft, slightly brushy edge, shadows tinted toward a hue instead of black, a
// rim of light on silhouettes, no realistic specular. Parameters come from the style profile.

import bevy_pbr::render::{
    pbr_fragment::pbr_input_from_standard_material,
    pbr_functions::alpha_discard,
    mesh_view_bindings as view_bindings,
    shadows,
    mesh_view_types,
};

@if(PREPASS_PIPELINE)
import bevy_pbr::{
    prepass::io::{VertexOutput, FragmentOutput},
    deferred::functions::deferred_output,
};
@else
import bevy_pbr::render::{
    forward_io::{VertexOutput, FragmentOutput},
    pbr_functions::main_pass_post_lighting_processing,
};

struct Toon {
    // rgb: shadow tint (multiplies lit colour in shadow), a: how dark shadows get (0..1).
    shadow: vec4<f32>,
    // rgb: rim colour, a: rim strength.
    rim: vec4<f32>,
    // x: band threshold (N·L), y: band softness, z: brush breakup, w: rim width (power).
    band: vec4<f32>,
    // x: brush scale (1/m), y: ambient lift, z: second (core) band darkness, w: exposure.
    extra: vec4<f32>,
}

@group(constants::MATERIAL_BIND_GROUP) @binding(100)
var<uniform> toon: Toon;

fn hash3(p: vec3<f32>) -> f32 {
    let q = fract(p * 0.1031);
    let r = q + dot(q, q.yzx + 33.33);
    return fract((r.x + r.y) * r.z);
}

// Value noise, for breaking up band edges like brush strokes.
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

@fragment
fn fragment(
    in: VertexOutput,
    @builtin(front_facing) is_front: bool,
) -> FragmentOutput {
    var pbr_input = pbr_input_from_standard_material(in, is_front);
    pbr_input.material.base_color = alpha_discard(
        pbr_input.material.flags,
        pbr_input.material.alpha_cutoff,
        pbr_input.material.base_color
    );
    var out: FragmentOutput;
@if(PREPASS_PIPELINE) {
    out = deferred_output(in, pbr_input);
} @else {
    let albedo = pbr_input.material.base_color;
    let N = normalize(pbr_input.N);
    let V = normalize(pbr_input.V);
    let p = pbr_input.world_position;
    let view_z = dot(vec4<f32>(
        view_bindings::view.view_from_world[0].z,
        view_bindings::view.view_from_world[1].z,
        view_bindings::view.view_from_world[2].z,
        view_bindings::view.view_from_world[3].z
    ), p);

    // The sun (first directional light) and its shadow.
    var sun = vec3<f32>(1.0);
    var lit = 0.0;
    if (view_bindings::lights.n_directional_lights > 0u) {
        let light = &view_bindings::lights.directional_lights[0];
        let L = (*light).direction_to_light;
        var shadow = 1.0;
        if (((*light).flags & mesh_view_types::DIRECTIONAL_LIGHT_FLAGS_SHADOWS_ENABLED_BIT) != 0u) {
            shadow = shadows::fetch_directional_shadow(0u, p, pbr_input.world_normal, view_z, in.position.xy);
        }
        // Lambert's 1/π, at the camera's exposure: the sunlit level of a white surface.
        sun = (*light).color.rgb * view_bindings::view.exposure / 3.14159265 * toon.extra.w;
        let ndl = dot(N, L);
        let brush = (noise3(p.xyz * toon.extra.x) - 0.5) * toon.band.z;
        let t = toon.band.x + brush;
        let band = smoothstep(t - toon.band.y, t + toon.band.y, ndl);
        // A darker core band where the surface turns fully away.
        let core = smoothstep(-0.35 + brush, -0.15 + brush, ndl);
        lit = band * shadow;
        let away = mix(toon.extra.z, 1.0, core);
        let shade = mix(toon.shadow.rgb * (1.0 - toon.shadow.a) + vec3(toon.extra.y), vec3(1.0), lit) * mix(away, 1.0, lit);
        var color = albedo.rgb * sun * shade;
        // Rim light on silhouettes, stronger on the lit side.
        let rim = pow(clamp(1.0 - max(dot(N, V), 0.0), 0.0, 1.0), toon.band.w) * toon.rim.a * (0.35 + 0.65 * lit);
        color = color + toon.rim.rgb * sun * rim;
        // Emission (fires, lamps) on top.
        color = color + pbr_input.material.emissive.rgb * view_bindings::view.exposure;
        out.color = vec4<f32>(color, albedo.a);
    } else {
        out.color = vec4<f32>(albedo.rgb * toon.extra.y, albedo.a);
    }
    out.color = main_pass_post_lighting_processing(pbr_input, out.color);
}
    return out;
}
