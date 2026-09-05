//! Shared browser/desktop Bevy presentation. No world stepping or skill effects run here.
mod network;
mod ui;
mod world;
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
    pub inspect: bool,
    pub world_visible: bool,
    pub overlays: bool,
    pub sessions_open: bool,
    pub runs: Vec<Value>,
    pub zoom: f32,
    pub camera_y: f32,
    pub follow: bool,
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
            inspect: false,
            world_visible: true,
            overlays: true,
            sessions_open: false,
            runs: vec![],
            zoom: 1.,
            camera_y: 0.,
            follow: false,
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
            .and_then(|p| p.iter().find(|p| p["id"] == self.snapshot["actor"]))
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
        .add_systems(Startup, (world::setup, ui::setup, network::start))
        .add_systems(
            Update,
            (
                network::tick,
                ui::interact,
                ui::scroll,
                keyboard,
                world::click,
                world::camera,
                resized,
                world::sync,
                ui::refresh,
            )
                .chain(),
        )
        .add_systems(
            PostUpdate,
            world::labels
                .after(bevy::camera::CameraUpdateSystems)
                .before(bevy::ui::UiSystems::Layout),
        )
        .run();
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
                        game.camera = (game.camera + d as f32).clamp(-10., 10.);
                        game.follow = false;
                    } else if !game.archive {
                        net.intent(json!({"skill":"move","destination":(game.own_position()+d).clamp(-10,10),"duration":1}));
                    }
                }
                KeyCode::KeyI => game.inspect = !game.inspect,
                KeyCode::KeyO => game.overlays = !game.overlays,
                KeyCode::KeyF => game.follow = !game.follow,
                KeyCode::Escape => {
                    game.inspect = false;
                    game.sessions_open = false;
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
