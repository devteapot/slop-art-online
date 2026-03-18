use bevy::prelude::*;

use shared::module_bindings::allocate_skill_point_reducer::allocate_skill_point;

use crate::constants::{ATTRS, POINTS_PER_LEVEL};
use crate::network::SpacetimeDb;
use crate::player::LocalPlayerStats;
use crate::skills::{
    attr_display, cooldown_remaining, get_attr_pts, points_allocated_client,
    LocalCooldowns, LocalSkillData, LocalSkills, MobilitySkillIds, SelectedSkill, SkillNameMap,
};

// --- Components ---

#[derive(Clone, Copy)]
pub enum StatKind { Health, Mana, Stamina }

#[derive(Component)]
pub struct StatBarFill(pub StatKind);

#[derive(Component)]
pub struct SkillSlotLabel(pub usize);

#[derive(Component)]
pub struct SkillSlotButton(pub usize);

#[derive(Component)]
pub struct SkillDetailPanel;

#[derive(Component)]
pub struct SkillDetailTitle;

#[derive(Component)]
pub struct SkillDetailPoints;

#[derive(Component)]
pub struct SkillAttrRow(pub usize);

#[derive(Component)]
pub struct AllocateButton(pub usize);

#[derive(Component)]
pub struct SkillDetailClose;

#[derive(Component)]
pub struct MobilitySlotLabel(pub usize); // 0 = Jump, 1 = Dash

// --- Setup ---

pub fn setup_hud(mut commands: Commands) {
    commands.spawn(Node {
        position_type: PositionType::Absolute,
        bottom: Val::Px(16.0),
        left: Val::Px(16.0),
        flex_direction: FlexDirection::Column,
        row_gap: Val::Px(4.0),
        ..default()
    }).with_children(|col| {
        spawn_stat_bar(col, "HP", Color::srgb(0.8, 0.15, 0.15), StatKind::Health);
        spawn_stat_bar(col, "MP", Color::srgb(0.2, 0.45, 0.9),  StatKind::Mana);
        spawn_stat_bar(col, "SP", Color::srgb(0.2, 0.75, 0.35), StatKind::Stamina);

        // Combat skill bar
        col.spawn(Node {
            flex_direction: FlexDirection::Row,
            column_gap: Val::Px(4.0),
            margin: UiRect::top(Val::Px(10.0)),
            ..default()
        }).with_children(|row| {
            for i in 0..4 {
                row.spawn((
                    Button,
                    SkillSlotButton(i),
                    Node {
                        width: Val::Px(90.0),
                        height: Val::Px(30.0),
                        justify_content: JustifyContent::Center,
                        align_items: AlignItems::Center,
                        ..default()
                    },
                    BackgroundColor(Color::srgba(0.0, 0.0, 0.0, 0.65)),
                )).with_children(|slot| {
                    slot.spawn((
                        SkillSlotLabel(i),
                        Text::new(format!("[{}] ---", i + 1)),
                        TextFont { font_size: 11.0, ..default() },
                        TextColor(Color::srgb(0.75, 0.75, 0.75)),
                    ));
                });
            }
        });

        // Mobility skill bar
        col.spawn(Node {
            flex_direction: FlexDirection::Row,
            column_gap: Val::Px(4.0),
            margin: UiRect::top(Val::Px(2.0)),
            ..default()
        }).with_children(|row| {
            for (i, key_label) in ["[Space]", "[Shift]"].iter().enumerate() {
                row.spawn((
                    Node {
                        width: Val::Px(90.0),
                        height: Val::Px(26.0),
                        justify_content: JustifyContent::Center,
                        align_items: AlignItems::Center,
                        ..default()
                    },
                    BackgroundColor(Color::srgba(0.0, 0.1, 0.2, 0.65)),
                )).with_children(|slot| {
                    slot.spawn((
                        MobilitySlotLabel(i),
                        Text::new(format!("{key_label} ---")),
                        TextFont { font_size: 10.0, ..default() },
                        TextColor(Color::srgb(0.6, 0.85, 1.0)),
                    ));
                });
            }
        });
    });

    // Skill detail panel (hidden by default)
    commands.spawn((
        SkillDetailPanel,
        Visibility::Hidden,
        Node {
            position_type: PositionType::Absolute,
            right: Val::Px(20.0),
            top: Val::Px(20.0),
            width: Val::Px(320.0),
            flex_direction: FlexDirection::Column,
            row_gap: Val::Px(6.0),
            padding: UiRect::all(Val::Px(12.0)),
            ..default()
        },
        BackgroundColor(Color::srgba(0.05, 0.05, 0.08, 0.92)),
    )).with_children(|panel| {
        // Header row: title + close
        panel.spawn(Node {
            flex_direction: FlexDirection::Row,
            justify_content: JustifyContent::SpaceBetween,
            align_items: AlignItems::Center,
            ..default()
        }).with_children(|hdr| {
            hdr.spawn((
                SkillDetailTitle,
                Text::new("Skill"),
                TextFont { font_size: 16.0, ..default() },
                TextColor(Color::WHITE),
            ));
            hdr.spawn((
                Button,
                SkillDetailClose,
                Node {
                    width: Val::Px(22.0),
                    height: Val::Px(22.0),
                    justify_content: JustifyContent::Center,
                    align_items: AlignItems::Center,
                    ..default()
                },
                BackgroundColor(Color::srgba(0.5, 0.1, 0.1, 0.8)),
            )).with_children(|btn| {
                btn.spawn((
                    Text::new("X"),
                    TextFont { font_size: 13.0, ..default() },
                    TextColor(Color::WHITE),
                ));
            });
        });

        // Points available
        panel.spawn((
            SkillDetailPoints,
            Text::new("Points: 0 / 0"),
            TextFont { font_size: 12.0, ..default() },
            TextColor(Color::srgb(0.8, 0.8, 0.4)),
        ));

        // Separator
        panel.spawn((
            Node {
                width: Val::Percent(100.0),
                height: Val::Px(1.0),
                ..default()
            },
            BackgroundColor(Color::srgba(1.0, 1.0, 1.0, 0.15)),
        ));

        // Attribute rows
        for (i, &(_, label)) in ATTRS.iter().enumerate() {
            panel.spawn(Node {
                flex_direction: FlexDirection::Row,
                justify_content: JustifyContent::SpaceBetween,
                align_items: AlignItems::Center,
                ..default()
            }).with_children(|row| {
                row.spawn((
                    SkillAttrRow(i),
                    Text::new(format!("{label}: 0")),
                    TextFont { font_size: 11.0, ..default() },
                    TextColor(Color::srgb(0.85, 0.85, 0.85)),
                    Node { width: Val::Px(240.0), ..default() },
                ));
                row.spawn((
                    Button,
                    AllocateButton(i),
                    Node {
                        width: Val::Px(26.0),
                        height: Val::Px(20.0),
                        justify_content: JustifyContent::Center,
                        align_items: AlignItems::Center,
                        ..default()
                    },
                    BackgroundColor(Color::srgba(0.2, 0.5, 0.2, 0.85)),
                )).with_children(|btn| {
                    btn.spawn((
                        Text::new("+"),
                        TextFont { font_size: 13.0, ..default() },
                        TextColor(Color::WHITE),
                    ));
                });
            });
        }
    });
}

pub fn spawn_stat_bar(parent: &mut ChildSpawnerCommands, label: &str, color: Color, kind: StatKind) {
    parent.spawn(Node {
        flex_direction: FlexDirection::Row,
        align_items: AlignItems::Center,
        column_gap: Val::Px(6.0),
        ..default()
    }).with_children(|row: &mut ChildSpawnerCommands| {
        row.spawn((
            Text::new(label),
            TextFont { font_size: 11.0, ..default() },
            TextColor(Color::WHITE),
            Node { width: Val::Px(20.0), ..default() },
        ));
        row.spawn((
            Node {
                width: Val::Px(180.0),
                height: Val::Px(12.0),
                ..default()
            },
            BackgroundColor(Color::srgba(0.0, 0.0, 0.0, 0.5)),
        )).with_children(|bar: &mut ChildSpawnerCommands| {
            bar.spawn((
                StatBarFill(kind),
                Node {
                    width: Val::Percent(100.0),
                    height: Val::Percent(100.0),
                    ..default()
                },
                BackgroundColor(color),
            ));
        });
    });
}

// --- Update systems ---

pub fn update_hud(
    local_stats: Res<LocalPlayerStats>,
    local_skills: Res<LocalSkills>,
    skill_name_map: Res<SkillNameMap>,
    local_cooldowns: Res<LocalCooldowns>,
    mobility_ids: Res<MobilitySkillIds>,
    mut stat_fills: Query<(&StatBarFill, &mut Node)>,
    mut skill_labels: Query<(&SkillSlotLabel, &mut Text), Without<MobilitySlotLabel>>,
    mut mobility_labels: Query<(&MobilitySlotLabel, &mut Text), Without<SkillSlotLabel>>,
) {
    for (fill, mut node) in &mut stat_fills {
        let ratio = match fill.0 {
            StatKind::Health  => local_stats.health  as f32 / local_stats.max_health.max(1)  as f32,
            StatKind::Mana    => local_stats.mana    as f32 / local_stats.max_mana.max(1)    as f32,
            StatKind::Stamina => local_stats.stamina as f32 / local_stats.max_stamina.max(1) as f32,
        };
        node.width = Val::Percent(ratio.clamp(0.0, 1.0) * 100.0);
    }

    for (slot, mut text) in &mut skill_labels {
        let skill_id = local_skills.0.get(slot.0).copied();
        let name = skill_id
            .and_then(|id| skill_name_map.0.get(&id))
            .map(|s| s.as_str())
            .unwrap_or("---");
        let cd = skill_id.map(|id| cooldown_remaining(&local_cooldowns, id)).unwrap_or(0.0);
        if cd > 0.1 {
            text.0 = format!("[{}] {:.1}s", slot.0 + 1, cd);
        } else {
            text.0 = format!("[{}] {}", slot.0 + 1, name);
        }
    }

    let mob_ids = [mobility_ids.jump, mobility_ids.dash];
    let mob_keys = ["[Space]", "[Shift]"];
    let mob_names = ["Jump", "Dash"];
    for (slot, mut text) in &mut mobility_labels {
        let name = mob_names[slot.0];
        let cd = mob_ids[slot.0].map(|id| cooldown_remaining(&local_cooldowns, id)).unwrap_or(0.0);
        if cd > 0.1 {
            text.0 = format!("{} {:.1}s", mob_keys[slot.0], cd);
        } else {
            text.0 = format!("{} {}", mob_keys[slot.0], name);
        }
    }
}

pub fn handle_skill_slot_clicks(
    slots: Query<(&Interaction, &SkillSlotButton), Changed<Interaction>>,
    local_skills: Res<LocalSkills>,
    mut selected: ResMut<SelectedSkill>,
) {
    for (interaction, slot) in &slots {
        if *interaction == Interaction::Pressed {
            selected.0 = local_skills.0.get(slot.0).copied();
        }
    }
}

pub fn handle_close_click(
    close_btns: Query<&Interaction, (Changed<Interaction>, With<SkillDetailClose>)>,
    mut selected: ResMut<SelectedSkill>,
) {
    for interaction in &close_btns {
        if *interaction == Interaction::Pressed {
            selected.0 = None;
        }
    }
}

pub fn handle_allocate_clicks(
    alloc_btns: Query<(&Interaction, &AllocateButton), Changed<Interaction>>,
    selected: Res<SelectedSkill>,
    conn: Option<Res<SpacetimeDb>>,
) {
    let Some(conn) = conn else { return };
    let Some(skill_id) = selected.0 else { return };

    for (interaction, btn) in &alloc_btns {
        if *interaction == Interaction::Pressed {
            let attr_key = ATTRS[btn.0].0.to_string();
            let _ = conn.0.reducers.allocate_skill_point(skill_id, attr_key);
        }
    }
}

pub fn update_skill_detail_panel(
    selected: Res<SelectedSkill>,
    local_skill_data: Res<LocalSkillData>,
    skill_name_map: Res<SkillNameMap>,
    mut panel: Query<&mut Visibility, With<SkillDetailPanel>>,
    mut title: Query<&mut Text, (With<SkillDetailTitle>, Without<SkillDetailPoints>, Without<SkillAttrRow>)>,
    mut points_text: Query<&mut Text, (With<SkillDetailPoints>, Without<SkillDetailTitle>, Without<SkillAttrRow>)>,
    mut attr_rows: Query<(&SkillAttrRow, &mut Text), (Without<SkillDetailTitle>, Without<SkillDetailPoints>)>,
) {
    let Ok(mut vis) = panel.single_mut() else { return };

    let Some(skill_id) = selected.0 else {
        *vis = Visibility::Hidden;
        return;
    };

    *vis = Visibility::Inherited;

    let name = skill_name_map.0.get(&skill_id).map(|s| s.as_str()).unwrap_or("???");
    if let Ok(mut t) = title.single_mut() { t.0 = name.to_string(); }

    let level = local_skill_data.levels.get(&skill_id).copied().unwrap_or(1);
    let total_pts = level * POINTS_PER_LEVEL;

    if let Some(attrs) = local_skill_data.attrs.get(&skill_id) {
        let used = points_allocated_client(attrs);
        let avail = (total_pts - used).max(0);

        if let Ok(mut t) = points_text.single_mut() {
            t.0 = format!("Points: {avail} free / {total_pts} total (lv{level})");
        }

        for (row, mut text) in &mut attr_rows {
            let pts = get_attr_pts(attrs, row.0);
            let label = ATTRS[row.0].1;
            text.0 = format!("{label}: {}", attr_display(row.0, pts));
        }
    } else {
        if let Ok(mut t) = points_text.single_mut() {
            t.0 = format!("Points: {total_pts} total (lv{level})");
        }
    }
}
