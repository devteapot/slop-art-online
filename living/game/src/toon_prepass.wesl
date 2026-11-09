// The toon material's prepass vertex shader (depth, normals and shadow maps): Bevy's prepass
// vertex shader (bevy_pbr 0.20.1 prepass/prepass.wesl) with the same wind sway as
// `toon_vertex.wesl`, so plants' depth, lines and shadows move with them. Motion vectors are
// not used by this game and are left out of the sway.

import bevy_pbr::{
    prepass::io::{Vertex, UncompressedVertex, VertexOutput, decompress_vertex},
    render::{
        mesh_bindings::mesh,
        mesh_functions,
        skinning,
        morph::{morph_position, morph_normal, morph_tangent},
        view_transformations::position_world_to_clip,
    },
};
import bevy_render::globals::Globals;

// In the prepass's view bind group the globals sit at binding 1 (bevy_pbr prepass/mod.rs).
@group(0) @binding(1) var<uniform> prepass_globals: Globals;

// Must match `Toon` in toon.wesl (only `atmo` and `shade` are read here).
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

@group(constants::MATERIAL_BIND_GROUP) @binding(100)
var<uniform> toon: Toon;

// Identical to `sway` in toon_vertex.wesl.
fn sway(world: vec3<f32>, origin: vec3<f32>, tag: u32, t: f32) -> vec3<f32> {
    let wind = toon.atmo.x;
    if ((tag & (1u << 25u)) == 0u || wind <= 0.0) {
        return world;
    }
    let kind = (tag >> 26u) & 3u;
    let h = max(world.y - origin.y, 0.0);
    var amp = h * h * 0.0016;
    if (kind == 0u) {
        amp = h * 0.16;
    } else if (kind == 1u) {
        amp = h * h * 0.02;
    }
    let phase = origin.x * 0.21 + origin.z * 0.17;
    let gust = 0.55 + 0.45 * sin(t * 0.45 - origin.x * 0.035 - origin.z * 0.02);
    let swing = sin(t * 1.6 + phase) * 0.7 + sin(t * 2.9 + phase * 1.7) * 0.3;
    let flutter = sin(t * 7.0 + world.x * 1.3 + world.z * 1.1) * 0.12 * min(h, 3.0) / 3.0;
    let dir = vec2<f32>(0.94, 0.34);
    let side = vec2<f32>(-dir.y, dir.x);
    let lean = amp * wind * (gust * 0.8 + swing * (0.35 + 0.25 * wind));
    let off = dir * lean + side * amp * wind * (flutter + swing * 0.25);
    return world + vec3<f32>(off.x, -abs(lean) * 0.15, off.y);
}

@if(MORPH_TARGETS)
fn morph_vertex(vertex_in: UncompressedVertex, instance_index: u32) -> UncompressedVertex {
    var vertex = vertex_in;
    let first_vertex = mesh[instance_index].first_vertex_index;
    let vertex_index = vertex.index - first_vertex;
    let morph_descriptor_index = mesh[instance_index].morph_descriptor_index;
    let weight_count = bevy_pbr::render::morph::layer_count(morph_descriptor_index);
    for (var i: u32 = 0u; i < weight_count; i ++) {
        let weight = bevy_pbr::render::morph::weight_at(i, morph_descriptor_index);
        if weight == 0.0 {
            continue;
        }
        vertex.position += weight * morph_position(vertex_index, i, morph_descriptor_index);
@if(VERTEX_NORMALS)
        vertex.normal += weight * morph_normal(vertex_index, i, morph_descriptor_index);
@if(VERTEX_TANGENTS)
        vertex.tangent += vec4(weight * morph_tangent(vertex_index, i, morph_descriptor_index), 0.0);
    }
    return vertex;
}

@vertex
fn vertex(vertex_no_morph: Vertex) -> VertexOutput {
    var out: VertexOutput;
    let uncompressed_vertex_no_morph = decompress_vertex(vertex_no_morph, vertex_no_morph.instance_index);
@if(MORPH_TARGETS)
    var vertex = morph_vertex(uncompressed_vertex_no_morph, vertex_no_morph.instance_index);
@else
    var vertex = uncompressed_vertex_no_morph;

    let mesh_world_from_local = mesh_functions::get_world_from_local(vertex_no_morph.instance_index);

@if(SKINNED)
    var world_from_local = skinning::skin_model(
        vertex.joint_indices,
        vertex.joint_weights,
        vertex_no_morph.instance_index
    );
@else
    var world_from_local = mesh_world_from_local;

    out.world_position = mesh_functions::mesh_position_local_to_world(world_from_local, vec4<f32>(vertex.position, 1.0));
    let tag = mesh_functions::get_tag(vertex_no_morph.instance_index);
    out.world_position = vec4<f32>(sway(out.world_position.xyz, mesh_world_from_local[3].xyz, tag, prepass_globals.time), 1.0);
    out.position = position_world_to_clip(out.world_position.xyz);
@if(UNCLIPPED_DEPTH_ORTHO_EMULATION) {
    out.unclipped_depth = out.position.z;
    out.position.z = min(out.position.z, 1.0);
}

@if(VERTEX_UVS_A)
    out.uv = vertex.uv;

@if(VERTEX_UVS_B)
    out.uv_b = vertex.uv_b;

@if(NORMAL_PREPASS_OR_DEFERRED_PREPASS) {
@if(VERTEX_NORMALS && SKINNED)
    out.world_normal = skinning::skin_normals(world_from_local, vertex.normal);
@elif(VERTEX_NORMALS)
    out.world_normal = mesh_functions::mesh_normal_local_to_world(
        vertex.normal,
        vertex_no_morph.instance_index
    );

@if(VERTEX_TANGENTS)
    out.world_tangent = mesh_functions::mesh_tangent_local_to_world(
        world_from_local,
        vertex.tangent,
        vertex_no_morph.instance_index
    );
}

@if(VERTEX_COLORS)
    out.color = vertex.color;

@if(MOTION_VECTOR_PREPASS) {
    let prev_model = mesh_functions::get_previous_world_from_local(vertex_no_morph.instance_index);
    out.previous_world_position = mesh_functions::mesh_position_local_to_world(
        prev_model,
        vec4<f32>(uncompressed_vertex_no_morph.position, 1.0)
    );
}

@if(VERTEX_OUTPUT_INSTANCE_INDEX)
    out.instance_index = vertex_no_morph.instance_index;

@if(VISIBILITY_RANGE_DITHER)
    out.visibility_range_dither = mesh_functions::get_visibility_range_dither_level(
        vertex_no_morph.instance_index, mesh_world_from_local[3]);

    return out;
}
