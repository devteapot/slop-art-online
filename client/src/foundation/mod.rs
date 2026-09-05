//! Shared browser/desktop Bevy presentation. No world stepping or skill effects run here.
mod network;
mod ui;
use bevy::prelude::*;
use network::Network;
use serde_json::{Value, json};

#[derive(Resource)]
pub struct Game {
    pub snapshot: Value,
    pub selected: u64,
    pub tab: usize,
    pub page: usize,
    pub event: Option<u64>,
    pub status: String,
    pub draft: String,
    pub typing: bool,
    pub archive: bool,
    pub dirty: bool,
    pub camera: f32,
    pub scroll: [f32; 2],
}
impl Default for Game {
    fn default() -> Self {
        Self {
            snapshot: Value::Null,
            selected: 1,
            tab: 0,
            page: 0,
            event: None,
            status: "Connecting to local development host…".into(),
            draft: String::new(),
            typing: false,
            archive: false,
            dirty: true,
            camera: 1.,
            scroll: [0.; 2],
        }
    }
}
impl Game {
    fn observer(&self) -> bool {
        self.snapshot["observer"] == true
    }
    fn player(&self) -> Value {
        self.snapshot["players"]
            .as_array()
            .and_then(|p| p.iter().find(|p| p["id"] == self.selected))
            .cloned()
            .unwrap_or(Value::Null)
    }
    fn own_position(&self) -> i32 {
        self.snapshot["players"]
            .as_array()
            .and_then(|p| p.iter().find(|p| p["id"] == 3))
            .and_then(|p| p["position"].as_i64())
            .unwrap_or(0) as i32
    }
}
pub fn run() {
    App::new()
        .insert_resource(ClearColor(Color::srgb(0.055, 0.087, 0.099)))
        .add_plugins(DefaultPlugins.set(WindowPlugin {
            primary_window: Some(Window {
                title: "SAO · Simulation development".into(),
                resolution: (1440, 900).into(),
                canvas: Some("#sao-canvas".into()),
                fit_canvas_to_parent: true,
                prevent_default_event_handling: true,
                ime_enabled: true,
                ..default()
            }),
            ..default()
        }))
        .init_resource::<Game>()
        .insert_non_send_resource(Network::default())
        .add_systems(Startup, (setup, ui::setup, network::start))
        .add_systems(
            Update,
            (
                network::tick,
                ui::interact,
                ui::scroll,
                keyboard,
                world_click,
                resized,
                world_render,
                ui::refresh,
            )
                .chain(),
        )
        .run();
}
#[derive(Component)]
struct WorldVisual;
fn setup(mut commands: Commands) {
    commands.spawn(Camera2d);
}
fn world_render(
    mut commands: Commands,
    game: Res<Game>,
    window: Single<&Window>,
    old: Query<Entity, With<WorldVisual>>,
) {
    if !game.dirty {
        return;
    }
    for entity in &old {
        commands.entity(entity).despawn();
    }
    let scale = ((window.width() - 680.) / 7.).clamp(42., 100.);
    let offset = -90.;
    for position in -10..=10 {
        let x = (position as f32 - game.camera) * scale + offset;
        let site = game.snapshot["sites"]
            .as_array()
            .and_then(|a| a.iter().find(|s| s["position"] == position));
        let danger = site.and_then(|s| s["hazard"].as_i64()).unwrap_or(0) > 0;
        let color = if danger {
            Color::srgb(0.37, 0.20, 0.16)
        } else if site.is_some() {
            Color::srgb(0.17, 0.30, 0.23)
        } else {
            Color::srgb(0.10, 0.16, 0.16)
        };
        commands.spawn((
            Sprite::from_color(color, Vec2::new(scale - 6., 160.)),
            Transform::from_xyz(x, -20., 0.),
            WorldVisual,
        ));
        let name = match position {
            0 => "Camp",
            1 => "Trail",
            2 => "Clearing",
            3 => "Grove",
            _ => "Land",
        };
        let food = site
            .and_then(|s| s["food"].as_i64())
            .map(|f| format!("food {f}"))
            .unwrap_or("unseen".into());
        commands.spawn((
            Text2d::new(format!(
                "{name} {position}\n{food}{}",
                if danger { "\nDANGER" } else { "" }
            )),
            TextFont {
                font_size: 13.,
                ..default()
            },
            TextColor(Color::srgb(0.71, 0.80, 0.73)),
            Transform::from_xyz(x, -135., 2.),
            WorldVisual,
        ));
    }
    if let Some(players) = game.snapshot["players"].as_array() {
        for p in players {
            let id = p["id"].as_u64().unwrap_or(0);
            let x = (p["position"].as_f64().unwrap_or(0.) as f32 - game.camera) * scale + offset;
            let y = -15. + (id as f32 - 2.) * 40.;
            let alive = p["health"].as_i64().unwrap_or(100) > 0;
            let color = if !alive {
                Color::srgb(0.37, 0.37, 0.36)
            } else if p["controller"] == "human" {
                Color::srgb(0.40, 0.68, 0.87)
            } else if p["controller"] == "other" {
                Color::srgb(0.62, 0.69, 0.65)
            } else {
                Color::srgb(0.91, 0.65, 0.33)
            };
            if id == game.selected {
                commands.spawn((
                    Sprite::from_color(Color::srgb(0.92, 0.93, 0.72), Vec2::new(32., 32.)),
                    Transform::from_xyz(x, y, 3.),
                    WorldVisual,
                ));
            }
            commands.spawn((
                Sprite::from_color(color, Vec2::new(24., 24.)),
                Transform::from_xyz(x, y, 4.),
                WorldVisual,
            ));
            commands.spawn((
                Text2d::new(p["name"].as_str().unwrap_or("Player")),
                TextFont {
                    font_size: 14.,
                    ..default()
                },
                TextColor(Color::WHITE),
                Transform::from_xyz(x, y + 23., 5.),
                WorldVisual,
            ));
        }
    }
}
fn world_click(
    mouse: Res<ButtonInput<MouseButton>>,
    window: Single<&Window>,
    mut game: ResMut<Game>,
    net: NonSend<Network>,
) {
    if !mouse.just_pressed(MouseButton::Left) || game.typing {
        return;
    }
    let Some(pos) = window.cursor_position() else {
        return;
    };
    if pos.x < 246.
        || pos.x > window.width() - 430.
        || pos.y < 100.
        || pos.y > window.height() - 130.
    {
        return;
    }
    let scale = ((window.width() - 680.) / 7.).clamp(42., 100.);
    let cell = ((pos.x - window.width() / 2. + 90.) / scale + game.camera)
        .round()
        .clamp(-10., 10.) as i32;
    if !game.observer() && !game.archive {
        net.intent(json!({"skill":"move","destination":cell,"duration":1}));
        game.status = format!("Move to {cell} submitted; waiting for authority");
    } else if let Some(p) = game.snapshot["players"]
        .as_array()
        .and_then(|a| a.iter().find(|p| p["position"] == cell))
    {
        game.selected = p["id"].as_u64().unwrap();
        game.page = 0;
    }
    game.dirty = true;
}
fn keyboard(
    mut input: MessageReader<bevy::input::keyboard::KeyboardInput>,
    keys: Res<ButtonInput<KeyCode>>,
    mut game: ResMut<Game>,
    net: NonSend<Network>,
) {
    for e in input.read() {
        if !e.state.is_pressed() {
            continue;
        }
        if game.typing {
            match e.key_code {
                KeyCode::Escape => game.typing = false,
                KeyCode::Backspace => {
                    game.draft.pop();
                }
                KeyCode::Enter => {
                    if !game.draft.trim().is_empty() {
                        net.intent(json!({"skill":"speak","text":game.draft,"duration":1}));
                        game.status =
                            "Speech submitted; listeners hear it when the skill executes".into();
                        game.draft.clear();
                        game.typing = false;
                    }
                }
                KeyCode::KeyA
                    if keys.pressed(KeyCode::ControlLeft) || keys.pressed(KeyCode::SuperLeft) =>
                {
                    game.draft.clear()
                }
                _ => {
                    if let Some(t) = &e.text {
                        if !t.chars().any(char::is_control) && game.draft.len() + t.len() <= 1000 {
                            game.draft.push_str(t);
                        }
                    }
                }
            }
        } else if !e.repeat {
            match e.key_code {
                KeyCode::ArrowLeft | KeyCode::ArrowRight => {
                    let d = if e.key_code == KeyCode::ArrowLeft {
                        -1
                    } else {
                        1
                    };
                    if game.observer() {
                        game.camera += d as f32;
                    } else if !game.archive {
                        net.intent(json!({"skill":"move","destination":(game.own_position()+d).clamp(-10,10),"duration":1}));
                    }
                }
                KeyCode::Enter if !game.observer() && !game.archive => game.typing = true,
                _ => {}
            }
        }
        game.dirty = true;
    }
}

fn resized(mut events: MessageReader<bevy::window::WindowResized>, mut game: ResMut<Game>) {
    if events.read().next().is_some() {
        game.dirty = true;
    }
}
