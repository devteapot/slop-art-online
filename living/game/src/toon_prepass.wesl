// The toon material's prepass vertex shader (depth, normals and shadow maps): Bevy's prepass
// vertex shader (bevy_pbr 0.20.1 prepass/prepass.wesl) with the same wind sway as
// `toon_vertex.wesl` (toon_light.wesl `sway`), so plants' depth, lines and shadows move with
// them. Motion vectors are not used by this game and are left out of the sway.

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
import living_game::toon_light::sway;

// In the prepass's view bind group the globals sit at binding 1 (bevy_pbr prepass/mod.rs).
@group(0) @binding(1) var<uniform> prepass_globals: Globals;

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

@if(VISIBILITY_RANGE_DITHER) {
    out.visibility_range_dither = mesh_functions::get_visibility_range_dither_level(
        vertex_no_morph.instance_index, mesh_world_from_local[3]);
    // A fade set by the client (fade.rs): bits 28-31 of the mesh's tag, 0 drawn to 15 almost gone,
    // dithered like a visibility range's transition.
    let fade = i32((mesh_functions::get_tag(vertex_no_morph.instance_index) >> 28u) & 15u);
    if (fade > 0) {
        out.visibility_range_dither = fade;
    }
}

    return out;
}
