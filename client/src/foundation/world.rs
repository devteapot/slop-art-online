//! Top-down presentation of subscribed state. No world stepping, physics or local skill effects.
use super::*;
use bevy::input::mouse::{AccumulatedMouseMotion, MouseScrollUnit, MouseWheel};
use std::collections::BTreeSet;

#[derive(Component)]
pub struct WorldCamera;
#[derive(Component)]
pub struct WorldEntity;
#[derive(Component)]
pub struct Character {
    id: u64,
    target: Vec3,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum LabelKey {
    Actor(u64),
    Site(i32),
}
#[derive(Component)]
pub struct Label {
    key: LabelKey,
    anchor: Vec3,
}
#[derive(Component)]
pub struct SelectionRing;
#[derive(Component)]
pub struct Terrain;
const CELL: f32 = 160.;
const GRASS: Color = Color::srgb(0.20, 0.32, 0.23);
const DARK: Color = Color::srgb(0.10, 0.17, 0.16);
const PATH: Color = Color::srgb(0.48, 0.43, 0.30);
fn actor_position(p: &Value) -> Vec3 {
    // Display lanes separate sprites sharing a location. They are not additional world coordinates.
    Vec3::new(
        p["position"].as_f64().unwrap_or(0.) as f32 * CELL,
        32. - (p["id"].as_u64().unwrap_or(1).saturating_sub(1) % 5) as f32 * 32.,
        10.,
    )
}
pub fn setup(mut commands: Commands) {
    commands.spawn((Camera2d, Transform::from_xyz(CELL, 0., 0.), WorldCamera));
}
fn tile(commands: &mut Commands, color: Color, at: Vec3, size: Vec2) -> Entity {
    commands
        .spawn((
            Sprite::from_color(color, size),
            Transform::from_translation(at),
            WorldEntity,
            Terrain,
        ))
        .id()
}
fn tree(commands: &mut Commands, x: f32, y: f32) {
    tile(
        commands,
        Color::srgb(0.12, 0.22, 0.16),
        Vec3::new(x + 4., y - 8., 1.),
        Vec2::new(44., 28.),
    );
    tile(
        commands,
        Color::srgb(0.37, 0.28, 0.19),
        Vec3::new(x, y - 16., 2.),
        Vec2::new(8., 20.),
    );
    tile(
        commands,
        Color::srgb(0.15, 0.27, 0.17),
        Vec3::new(x, y, 3.),
        Vec2::new(44., 28.),
    );
    tile(
        commands,
        Color::srgb(0.27, 0.42, 0.22),
        Vec3::new(x, y + 12., 4.),
        Vec2::new(32., 28.),
    );
    tile(
        commands,
        Color::srgb(0.38, 0.51, 0.28),
        Vec3::new(x - 6., y + 21., 5.),
        Vec2::new(12., 10.),
    );
}
fn label(
    commands: &mut Commands,
    existing: &mut Query<(Entity, &mut Label, &mut Text)>,
    key: LabelKey,
    text: String,
    anchor: Vec3,
) {
    let text = text.replace('·', "|").replace(['“', '”'], "\"");
    if let Some((_, mut label, mut current)) = existing.iter_mut().find(|(_, l, _)| l.key == key) {
        if label.anchor != anchor {
            label.anchor = anchor;
        }
        if current.0 != text {
            current.0 = text;
        }
        return;
    }
    commands.spawn((
        Text::new(text),
        TextFont {
            font_size: 13.,
            ..default()
        },
        TextColor(Color::srgb(0.94, 0.94, 0.81)),
        Node {
            position_type: PositionType::Absolute,
            left: px(0),
            top: px(0),
            padding: UiRect::all(px(5)),
            max_width: px(220),
            ..default()
        },
        BackgroundColor(Color::srgba(0.035, 0.065, 0.065, 0.86)),
        Label { key, anchor },
        Visibility::Hidden,
    ));
}
pub fn sync(
    mut commands: Commands,
    game: Res<Game>,
    old: Query<Entity, With<Terrain>>,
    mut existing_labels: Query<(Entity, &mut Label, &mut Text)>,
    mut rings: Query<(&ChildOf, &mut Visibility), With<SelectionRing>>,
    mut terrain_state: Local<Value>,
    mut actors: Query<(Entity, &mut Character, &mut Transform, &mut Sprite)>,
    time: Res<Time>,
    mut shown_run: Local<String>,
) {
    let run = game.snapshot["run"].as_str().unwrap_or("");
    let switched = shown_run.as_str() != run;
    *shown_run = run.into();
    if game.dirty {
        let terrain = json!([
            run,
            game.world_visible,
            game.snapshot["sites"].as_array().map(|sites| sites
                .iter()
                .map(|s| json!([s["position"], s["food"], s["hazard"]]))
                .collect::<Vec<_>>())
        ]);
        let terrain_changed = *terrain_state != terrain;
        *terrain_state = terrain;
        if terrain_changed {
            for e in &old {
                commands.entity(e).despawn();
            }
            if game.world_visible {
                for pos in -10..=10 {
                    let x = pos as f32 * CELL;
                    let site = game.snapshot["sites"]
                        .as_array()
                        .and_then(|sites| sites.iter().find(|s| s["position"] == pos));
                    let known = site.is_some();
                    let hazard = site.and_then(|s| s["hazard"].as_i64()).unwrap_or(0) > 0;
                    tile(
                        &mut commands,
                        if known { GRASS } else { DARK },
                        Vec3::new(x, 0., 0.),
                        Vec2::new(CELL, 448.),
                    );
                    // Flat, deterministic tiles. Only the authority supplies resources and hazards.
                    for col in -2..=2 {
                        for row in -6i32..=6 {
                            let tx = x + col as f32 * 32.;
                            let ty = row as f32 * 32.;
                            if row.abs() <= 1 {
                                tile(
                                    &mut commands,
                                    if hazard {
                                        Color::srgb(0.46, 0.29, 0.23)
                                    } else if known {
                                        PATH
                                    } else {
                                        Color::srgb(0.20, 0.25, 0.22)
                                    },
                                    Vec3::new(tx, ty, 0.2),
                                    Vec2::splat(32.),
                                );
                                if known && (col + row + pos) % 3 == 0 {
                                    tile(
                                        &mut commands,
                                        Color::srgba(0.68, 0.60, 0.41, 0.35),
                                        Vec3::new(tx + 7., ty - 6., 0.3),
                                        Vec2::new(8., 3.),
                                    );
                                }
                            } else if known && (col + row + pos) % 3 == 0 {
                                tile(
                                    &mut commands,
                                    Color::srgb(0.30, 0.41, 0.25),
                                    Vec3::new(tx, ty, 0.2),
                                    Vec2::new(3., 7.),
                                );
                                tile(
                                    &mut commands,
                                    Color::srgb(0.30, 0.41, 0.25),
                                    Vec3::new(tx + 5., ty - 2., 0.2),
                                    Vec2::new(3., 4.),
                                );
                            }
                        }
                    }
                    if known {
                        for (dx, y) in [(-46., 164.), (45., 190.), (28., -174.)] {
                            tree(&mut commands, x + dx, y);
                        }
                        let food = site.and_then(|s| s["food"].as_i64()).unwrap_or(0);
                        for i in 0..food.clamp(0, 16) {
                            let at = Vec3::new(
                                x - 40. + (i % 4) as f32 * 13.,
                                -95. - (i / 4) as f32 * 12.,
                                2.,
                            );
                            tile(
                                &mut commands,
                                Color::srgb(0.37, 0.46, 0.22),
                                at,
                                Vec2::new(12., 10.),
                            );
                            tile(
                                &mut commands,
                                Color::srgb(0.85, 0.72, 0.33),
                                at + Vec3::new(0., 2., 1.),
                                Vec2::new(8., 6.),
                            );
                        }
                    }
                }
            }
        }
        let mut wanted = BTreeSet::new();
        if game.world_visible {
            if let Some(sites) = game.snapshot["sites"].as_array() {
                for site in sites {
                    let pos = site["position"].as_i64().unwrap_or(0) as i32;
                    let name = match pos {
                        0 => "Camp",
                        1 => "Trail",
                        2 => "Clearing",
                        3 => "Grove",
                        _ => "Land",
                    };
                    let age = site["observed_tick"]
                        .as_u64()
                        .map(|t| format!(" · seen t{t}"))
                        .unwrap_or_default();
                    let food = site["food"].as_i64().unwrap_or(0);
                    let hazard = site["hazard"].as_i64().unwrap_or(0) > 0;
                    let key = LabelKey::Site(pos);
                    wanted.insert(key);
                    label(
                        &mut commands,
                        &mut existing_labels,
                        key,
                        format!(
                            "{name} {pos} · food {food}{age}{}",
                            if hazard { " · danger" } else { "" }
                        ),
                        Vec3::new(pos as f32 * CELL, -140., 8.),
                    );
                }
            }
        }
        let players = game.snapshot["players"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        for (entity, character, _, _) in &mut actors {
            if !game.world_visible || !players.iter().any(|p| p["id"] == character.id) {
                commands.entity(entity).despawn();
            }
        }
        if game.world_visible {
            for p in players {
                let id = p["id"].as_u64().unwrap_or(0);
                let dead = p["health"].as_i64() == Some(0);
                let target = actor_position(&p);
                let color = if dead {
                    Color::srgb(0.40, 0.43, 0.40)
                } else if p["controller"] == "human" {
                    Color::srgb(0.32, 0.63, 0.85)
                } else if p["controller"] == "other" {
                    Color::srgb(0.54, 0.63, 0.55)
                } else {
                    Color::srgb(0.87, 0.57, 0.28)
                };
                let rotation = if dead {
                    Quat::from_rotation_z(std::f32::consts::FRAC_PI_2)
                } else {
                    Quat::IDENTITY
                };
                if let Some((_, mut character, mut transform, mut sprite)) =
                    actors.iter_mut().find(|(_, c, _, _)| c.id == id)
                {
                    character.target = target;
                    if switched {
                        transform.translation = target;
                    }
                    transform.rotation = rotation;
                    sprite.color = color;
                } else {
                    commands
                        .spawn((
                            Sprite::from_color(color, Vec2::new(18., 20.)),
                            Transform::from_translation(target).with_rotation(rotation),
                            WorldEntity,
                            Character { id, target },
                        ))
                        .with_children(|p| {
                            p.spawn((SelectionRing, Visibility::Hidden, Transform::default()))
                                .with_children(|ring| {
                                    for (dx, dy, w, h) in [
                                        (-16., 0., 2., 40.),
                                        (16., 0., 2., 40.),
                                        (0., -20., 34., 2.),
                                        (0., 20., 34., 2.),
                                    ] {
                                        ring.spawn((
                                            Sprite::from_color(
                                                Color::srgb(0.94, 0.87, 0.57),
                                                Vec2::new(w, h),
                                            ),
                                            Transform::from_xyz(dx, dy, -1.),
                                        ));
                                    }
                                });
                            for (color, x, y, z, w, h) in [
                                (Color::srgb(0.87, 0.73, 0.54), 0., 15., 1., 14., 12.),
                                (Color::srgb(0.25, 0.21, 0.18), 0., 22., 2., 16., 6.),
                                (Color::srgb(0.18, 0.21, 0.22), -5., -13., 1., 6., 8.),
                                (Color::srgb(0.18, 0.21, 0.22), 5., -13., 1., 6., 8.),
                                (Color::srgb(0.20, 0.18, 0.15), -3., 15., 2., 2., 2.),
                                (Color::srgb(0.20, 0.18, 0.15), 3., 15., 2., 2., 2.),
                            ] {
                                p.spawn((
                                    Sprite::from_color(color, Vec2::new(w, h)),
                                    Transform::from_xyz(x, y, z),
                                ));
                            }
                        });
                }
                {
                    let recent = game.snapshot["events"].as_array().and_then(|events| {
                        events.iter().rev().find(|e| {
                            game.observer()
                                && e["actor"] == id
                                && matches!(e["kind"].as_str(), Some("skill_result" | "speech"))
                        })
                    });
                    let action = recent
                        .map(|e| {
                            format!(
                                "\n#{} t{} · {} {}",
                                e["id"],
                                e["tick"],
                                e["data"]["skill"].as_str().unwrap_or(
                                    if e["kind"] == "skill_result" {
                                        "action"
                                    } else {
                                        "speech"
                                    }
                                ),
                                e["data"]["status"].as_str().unwrap_or("")
                            )
                        })
                        .unwrap_or_default();
                    let health = p["health"]
                        .as_i64()
                        .map(|h| {
                            if id == game.selected {
                                format!("\nHP {h} · carrying {}", p["food"])
                            } else {
                                String::new()
                            }
                        })
                        .unwrap_or_default();
                    let speech = game.snapshot["events"]
                        .as_array()
                        .and_then(|events| {
                            events.iter().rev().find(|e| {
                                (if game.observer() {
                                    e["actor"] == id
                                } else {
                                    e["data"]["speaker"] == p["name"]
                                }) && e["kind"] == "speech"
                                    && game.snapshot["tick"]
                                        .as_u64()
                                        .unwrap_or(0)
                                        .saturating_sub(e["tick"].as_u64().unwrap_or(0))
                                        <= 2
                            })
                        })
                        .and_then(|e| e["data"]["text"].as_str())
                        .map(|t| format!("\n“{}”", t.chars().take(90).collect::<String>()))
                        .unwrap_or_default();
                    let key = LabelKey::Actor(id);
                    wanted.insert(key);
                    label(
                        &mut commands,
                        &mut existing_labels,
                        key,
                        format!(
                            "{}{health}{action}{speech}",
                            p["name"].as_str().unwrap_or("Character")
                        ),
                        actor_position(&p) + Vec3::Y * 34.,
                    );
                }
            }
        }
        for (entity, label, _) in &mut existing_labels {
            if !wanted.contains(&label.key) {
                commands.entity(entity).despawn();
            }
        }
    }
    for (parent, mut visibility) in &mut rings {
        let selected = actors
            .get(parent.parent())
            .is_ok_and(|(_, actor, _, _)| actor.id == game.selected);
        visibility.set_if_neq(if selected && game.world_visible {
            Visibility::Inherited
        } else {
            Visibility::Hidden
        });
    }
    // Interpolate confirmed movement only. Dead/hidden characters never acquire local behavior.
    for (_, character, mut transform, _) in &mut actors {
        transform.translation = transform
            .translation
            .lerp(character.target, (time.delta_secs() * 9.).min(1.));
    }
}
pub fn labels(
    camera: Single<(&Camera, &Transform), With<WorldCamera>>,
    mut labels: Query<(&Label, &ComputedNode, &mut UiTransform, &mut Visibility)>,
    actors: Query<(&Character, &Transform)>,
    game: Res<Game>,
) {
    let mut occupied: Vec<Rect> = vec![];
    let mut ordered: Vec<_> = labels.iter_mut().collect();
    ordered.sort_by_key(|(label, _, _, _)| label.key);
    for (label, computed, mut transform, mut visibility) in ordered {
        let anchor = match label.key {
            LabelKey::Actor(id) => actors
                .iter()
                .find(|(actor, _)| actor.id == id)
                .map(|(_, t)| t.translation + Vec3::Y * 34.)
                .unwrap_or(label.anchor),
            LabelKey::Site(_) => label.anchor,
        };
        if let Ok(pos) = camera
            .0
            .world_to_viewport(&GlobalTransform::from(*camera.1), anchor)
        {
            let size = computed.size() * computed.inverse_scale_factor();
            if size.x == 0. || size.y == 0. {
                *visibility = Visibility::Hidden;
                continue;
            }
            let mut top_left = Vec2::new(pos.x - size.x / 2., pos.y - size.y);
            // Move overlapping callouts upward; keep their world anchor unchanged.
            for _ in 0..20 {
                let rect = Rect::from_corners(top_left, top_left + size);
                if let Some(other) = occupied.iter().find(|r| {
                    r.min.x < rect.max.x
                        && r.max.x > rect.min.x
                        && r.min.y < rect.max.y
                        && r.max.y > rect.min.y
                }) {
                    top_left.y = other.min.y - size.y - 5.;
                } else {
                    break;
                }
            }
            occupied.push(Rect::from_corners(top_left, top_left + size));
            // Translation moves cached UI geometry without dirtying the layout Node.
            let translation = Val2::px(top_left.x.round(), top_left.y.round());
            if transform.translation != translation {
                transform.translation = translation;
            }
            *visibility = if game.world_visible && game.overlays {
                Visibility::Inherited
            } else {
                Visibility::Hidden
            };
        } else {
            *visibility = Visibility::Hidden;
        }
    }
}

pub fn camera(
    mut game: ResMut<Game>,
    mut camera: Single<(&mut Transform, &mut Projection), With<WorldCamera>>,
    keys: Res<ButtonInput<KeyCode>>,
    mouse: Res<ButtonInput<MouseButton>>,
    motion: Res<AccumulatedMouseMotion>,
    mut wheel: MessageReader<MouseWheel>,
    window: Single<&Window>,
    time: Res<Time>,
) {
    let over_ui = window
        .cursor_position()
        .is_some_and(|p| super::ui::captures(&game, p, window.width(), window.height()));
    for e in wheel.read() {
        if !over_ui {
            game.zoom = (game.zoom
                * (1.
                    - e.y
                        * match e.unit {
                            MouseScrollUnit::Line => 0.1,
                            _ => 0.002,
                        }))
            .clamp(0.5, 2.5);
        }
    }
    if !game.typing && game.world_visible {
        if mouse.pressed(MouseButton::Right) && !over_ui {
            game.camera -= motion.delta.x * game.zoom / CELL;
            game.camera_y += motion.delta.y * game.zoom;
            game.follow = false;
        }
        let dx = i32::from(keys.pressed(KeyCode::KeyD)) - i32::from(keys.pressed(KeyCode::KeyA));
        let dy = i32::from(keys.pressed(KeyCode::KeyW)) - i32::from(keys.pressed(KeyCode::KeyS));
        if dx != 0 || dy != 0 {
            game.camera += dx as f32 * time.delta_secs() * 240. / CELL;
            game.camera_y += dy as f32 * time.delta_secs() * 240.;
            game.follow = false;
        }
    }
    game.camera = game.camera.clamp(-10., 10.);
    game.camera_y = game.camera_y.clamp(-350., 350.);
    if game.follow {
        let p = game.player();
        if let Some(x) = p["position"].as_f64() {
            game.camera = x as f32;
            game.camera_y = actor_position(&p).y;
        }
    }
    camera.0.translation = Vec3::new((game.camera * CELL).round(), game.camera_y.round(), 0.);
    if let Projection::Orthographic(projection) = &mut *camera.1 {
        projection.scale = game.zoom;
    }
}
pub fn click(
    mouse: Res<ButtonInput<MouseButton>>,
    window: Single<&Window>,
    camera: Single<(&Camera, &GlobalTransform), With<WorldCamera>>,
    mut game: ResMut<Game>,
    net: NonSend<Network>,
) {
    if !mouse.just_pressed(MouseButton::Left) || game.typing || !game.world_visible {
        return;
    }
    let Some(pos) = window.cursor_position() else {
        return;
    };
    if super::ui::captures(&game, pos, window.width(), window.height()) {
        return;
    }
    if game.observer() || game.archive {
        let selected = game.snapshot["players"].as_array().and_then(|players| {
            players
                .iter()
                .filter_map(|p| {
                    let screen = camera
                        .0
                        .world_to_viewport(camera.1, actor_position(p))
                        .ok()?;
                    let distance = screen.distance(pos);
                    (distance < 24.).then_some((p["id"].as_u64()?, distance))
                })
                .min_by(|a, b| a.1.total_cmp(&b.1))
        });
        if let Some((id, _)) = selected {
            game.selected = id;
            game.inspect = true;
            game.page = 0;
            game.event = None;
            game.dirty = true;
        }
    } else if let Ok(point) = camera.0.viewport_to_world_2d(camera.1, pos) {
        // Only the lane is actionable: surrounding scenery does not invent 2D navigation rules.
        if point.y.abs() <= 80. {
            let cell = (point.x / CELL).round() as i32;
            net.intent(json!({"skill":"move","destination":cell,"duration":1}));
            game.status = format!("Move to {cell} submitted; waiting for authority");
            game.dirty = true;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entities<T: Component>(app: &mut App) -> BTreeSet<Entity> {
        app.world_mut()
            .query_filtered::<Entity, With<T>>()
            .iter(app.world())
            .collect()
    }

    #[test]
    fn repeated_snapshots_retain_labels_and_scenery_then_clean_up_hidden_world() {
        let mut app = App::new();
        let mut game = Game::default();
        game.snapshot = json!({"run":"render-fixture","observer":true,
            "players":[{"id":1,"name":"Mira","position":0,"health":100,"food":2}],
            "sites":[{"position":0,"food":6,"hazard":0}],"events":[]});
        app.insert_resource(game)
            .init_resource::<Time>()
            .add_systems(Update, sync);
        app.update();
        let labels = entities::<Label>(&mut app);
        let terrain = entities::<Terrain>(&mut app);
        assert_eq!(labels.len(), 2);
        assert!(!terrain.is_empty());
        for entity in &labels {
            app.world_mut()
                .entity_mut(*entity)
                .insert(Visibility::Inherited);
        }
        for tick in 1..=100 {
            app.world_mut().resource_mut::<Game>().snapshot["time_ms"] = json!(tick * 50);
            app.update();
            assert_eq!(entities::<Label>(&mut app), labels);
            assert_eq!(entities::<Terrain>(&mut app), terrain);
            for entity in &labels {
                assert_eq!(
                    *app.world().get::<Visibility>(*entity).unwrap(),
                    Visibility::Inherited
                );
            }
        }
        app.world_mut().resource_mut::<Game>().snapshot["players"][0]["health"] = json!(75);
        app.world_mut().resource_mut::<Game>().snapshot["sites"][0]["food"] = json!(5);
        app.update();
        assert_eq!(entities::<Label>(&mut app), labels);
        assert!(
            labels
                .iter()
                .any(|e| app.world().get::<Text>(*e).unwrap().0.contains("HP 75"))
        );
        app.world_mut().resource_mut::<Game>().overlays = false;
        app.update();
        assert_eq!(entities::<Label>(&mut app), labels);
        app.world_mut().resource_mut::<Game>().world_visible = false;
        app.update();
        assert!(entities::<Label>(&mut app).is_empty());
        assert!(entities::<Terrain>(&mut app).is_empty());
        assert!(entities::<Character>(&mut app).is_empty());
        assert!(entities::<SelectionRing>(&mut app).is_empty());
    }
}
