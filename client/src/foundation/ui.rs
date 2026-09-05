use super::*;
use spacetimedb_sdk::DbContext;
#[derive(Component)]
pub(super) struct UiRoot;
#[derive(Component)]
pub struct Panel(usize);
#[derive(Component, Clone)]
pub enum Click {
    Select(u64),
    Tab(usize),
    Mode,
    Step,
    Play,
    New,
    Archive,
    Live,
    Left,
    Right,
    Gather,
    Eat,
    Rest,
    Speak,
    Prev,
    Next,
    Event(u64),
    Reconnect,
}
const INK: Color = Color::srgb(0.86, 0.91, 0.86);
const MUTED: Color = Color::srgb(0.55, 0.65, 0.62);
const PANEL: Color = Color::srgb(0.075, 0.12, 0.13);
fn text(p: &mut ChildSpawnerCommands, s: impl Into<String>, size: f32, color: Color) {
    let s = s
        .into()
        .replace('·', "|")
        .replace('→', ">")
        .replace('←', "<")
        .replace('…', "...")
        .replace('—', "-")
        .replace('●', "*")
        .replace('○', " ")
        .replace('▶', ">")
        .replace('‹', "<")
        .replace('›', ">")
        .replace('▏', "|")
        .replace(['“', '”'], "\"")
        .replace('’', "'");
    p.spawn((
        Text::new(s),
        TextFont {
            font_size: size,
            ..default()
        },
        TextColor(color),
        Node {
            max_width: percent(100),
            flex_shrink: 0.,
            ..default()
        },
    ));
}
fn button(p: &mut ChildSpawnerCommands, label: impl Into<String>, click: Click, active: bool) {
    p.spawn((
        Button,
        click,
        Node {
            padding: UiRect::axes(px(11), px(8)),
            flex_shrink: 0.,
            margin: UiRect::bottom(px(4)),
            border_radius: BorderRadius::all(px(5)),
            ..default()
        },
        BackgroundColor(if active {
            Color::srgb(0.23, 0.38, 0.32)
        } else {
            Color::srgb(0.13, 0.20, 0.21)
        }),
    ))
    .with_children(|p| text(p, label, 14., INK));
}
fn row() -> Node {
    Node {
        display: Display::Flex,
        flex_direction: FlexDirection::Row,
        flex_wrap: FlexWrap::Wrap,
        column_gap: px(6),
        row_gap: px(2),
        ..default()
    }
}
fn column() -> Node {
    Node {
        display: Display::Flex,
        flex_direction: FlexDirection::Column,
        row_gap: px(10),
        ..default()
    }
}
fn number(v: &Value) -> String {
    v.as_i64().map(|n| n.to_string()).unwrap_or("?".into())
}
fn title(p: &mut ChildSpawnerCommands, label: &str) {
    text(p, label, 12., Color::srgb(0.66, 0.78, 0.57));
}
pub fn setup(mut game: ResMut<Game>) {
    game.dirty = true;
}
pub fn refresh(mut commands: Commands, mut game: ResMut<Game>, roots: Query<Entity, With<UiRoot>>) {
    if !game.dirty {
        return;
    }
    game.dirty = false;
    for e in &roots {
        commands.entity(e).despawn();
    }
    let p = game.player();
    let mode = game.snapshot["evidence_mode"]
        .as_str()
        .unwrap_or("connecting");
    let evidence = if game.archive {
        "ARCHIVE · actual model output · read-only"
    } else if mode == "live_fixture" {
        "LIVE · explicit fixture policy · no inference"
    } else if mode == "live_model" {
        "LIVE · configured model reasoning"
    } else {
        "CONNECTING"
    };
    commands.spawn((UiRoot,Node{position_type:PositionType::Absolute,width:percent(100),height:percent(100),..default()})).with_children(|root|{
  root.spawn((Node{position_type:PositionType::Absolute,left:px(0),right:px(0),top:px(0),height:px(78),padding:UiRect::axes(px(24),px(14)),justify_content:JustifyContent::SpaceBetween,..row()},BackgroundColor(PANEL))).with_children(|bar|{
   bar.spawn(column()).with_children(|p|{text(p,"S A O  /  FIELD STATION",23.,INK);text(p,evidence,12.,Color::srgb(0.75,0.72,0.45));});
   bar.spawn(column()).with_children(|p|{text(p,format!("TICK {} / {}    {}",number(&game.snapshot["tick"]),number(&game.snapshot["max_ticks"]),if game.snapshot["stopped"]==true{"FINISHED"}else if game.snapshot["paused"]==true{"PAUSED"}else{"RUNNING"}),18.,INK);text(p,if game.observer(){"Observer: world truth + individual understanding"}else{"Participant: your own perceptions + shared skills"},12.,MUTED);});
  });
  root.spawn((Node{position_type:PositionType::Absolute,left:px(12),top:px(92),bottom:px(112),width:px(222),padding:UiRect::all(px(14)),overflow:Overflow::scroll_y(),..column()},BackgroundColor(PANEL),Panel(0),ScrollPosition(Vec2::new(0.,game.scroll[0])))).with_children(|left|{
   title(left,"CHARACTERS");
   if let Some(players)=game.snapshot["players"].as_array(){for player in players{let id=player["id"].as_u64().unwrap_or(0);button(left,format!("{}  {}\n{} · position {}",if id==game.selected{"●"}else{"○"},player["name"].as_str().unwrap_or("Player"),player["controller"].as_str().unwrap_or(""),number(&player["position"])),Click::Select(id),id==game.selected);}}
   title(left,"DEVELOPMENT MODE");
   if !game.archive{button(left,if game.observer(){"Participate as You"}else{"Return to observer"},Click::Mode,false);}
   if game.observer()&&!game.archive {
    left.spawn(row()).with_children(|p|{button(p,"Step",Click::Step,false);button(p,if game.snapshot["paused"]==true{"Resume"}else{"Pause"},Click::Play,false);});
    button(left,if mode=="live_model"{"Fresh model run"}else{"Fresh fixture run"},Click::New,false);
    button(left,"Recorded model policy",Click::Archive,false);
   }
   if game.archive {button(left,"Back to live run",Click::Live,false);}
   button(left,"Reconnect",Click::Reconnect,false);
   text(left,"The authority owns every tick, skill and consequence.",12.,MUTED);
   text(left,if game.archive{"History is read-only. This is not a live playable run."}else if game.observer(){"Click a world cell to select its character. Arrow keys pan the field."}else{"Click a field cell or use arrow keys to move. Enter opens speech. If paused, switch to observer to resume."},12.,MUTED);
  });
  root.spawn((Node{position_type:PositionType::Absolute,right:px(12),top:px(92),bottom:px(112),width:px(404),padding:UiRect::all(px(16)),overflow:Overflow::scroll_y(),..column()},BackgroundColor(PANEL),Panel(1),ScrollPosition(Vec2::new(0.,game.scroll[1])))).with_children(|panel|{
   text(panel,p["name"].as_str().unwrap_or("Select a character"),24.,INK);
   text(panel,format!("{} · {}",p["role"].as_str().unwrap_or("perceived character"),if p["health"]==0{"dead — history retained"}else{"individual understanding"}),12.,MUTED);
   panel.spawn(row()).with_children(|p|{button(p,"Mind",Click::Tab(0),game.tab==0);button(p,"Policy",Click::Tab(1),game.tab==1);button(p,"History",Click::Tab(2),game.tab==2);});
   match game.tab {
    0=>mind(panel,&p),
    1=>tree(panel,&p,&game),
    _=>history(panel,&game),
   }
  });
  root.spawn(Node{position_type:PositionType::Absolute,left:px(250),right:px(432),top:px(104),..column()}).with_children(|p|{
   text(p,"THE CLEARING",14.,Color::srgb(0.53,0.69,0.56));
   text(p,if game.observer(){"Shared world · amber AI · blue human\nDanger shown here is observer truth."}else{"Your view · unseen sites stay unknown\nMovement, food and speech use authoritative skills."},13.,MUTED);
  });
  root.spawn((Node{position_type:PositionType::Absolute,left:px(12),right:px(12),bottom:px(12),height:px(88),padding:UiRect::axes(px(16),px(10)),..column()},BackgroundColor(PANEL))).with_children(|bottom|{
   if !game.observer()&&!game.archive {bottom.spawn(row()).with_children(|p|{button(p,"← Move",Click::Left,false);button(p,"Move →",Click::Right,false);button(p,"Gather",Click::Gather,false);button(p,"Eat",Click::Eat,false);button(p,"Rest",Click::Rest,false);button(p,if game.typing{"Typing… Enter to send"}else{"Speak…"},Click::Speak,game.typing);});}
   text(bottom,if game.typing{format!("Say: {}▏",game.draft)}else{game.status.clone()},14.,if game.typing{INK}else{MUTED});
   if game.observer(){text(bottom,format!("{}   ·   {}",game.snapshot["run"].as_str().unwrap_or("Authoritative connection pending"),if game.archive{"preserved model evidence"}else{"Bevy WASM game view · server-enforced role"}),12.,MUTED);}
  });
 });
}
fn mind(panel: &mut ChildSpawnerCommands, p: &Value) {
    title(panel, "MOTIVE / GOAL");
    text(
        panel,
        p["motive"]
            .as_str()
            .unwrap_or("This character's private mind is not visible in participant mode."),
        14.,
        INK,
    );
    if p.get("health").is_none() {
        return;
    }
    title(panel, "NEEDS & RESOURCES");
    for (label, key) in [
        ("Health", "health"),
        ("Hunger", "hunger"),
        ("Energy", "energy"),
        ("Carried food", "food"),
        ("Fear", "fear"),
    ] {
        panel
            .spawn(Node {
                justify_content: JustifyContent::SpaceBetween,
                ..row()
            })
            .with_children(|row| {
                text(row, label, 14., MUTED);
                text(row, number(&p[key]), 14., INK);
            });
    }
    title(panel, "CURRENT APPROACH");
    text(
        panel,
        if p["current_approach"].is_null() {
            "Awaiting an intent or new reasoning".into()
        } else {
            format!(
                "Decision #{} | {}\n{}",
                number(&p["current_approach"]["decision"]),
                p["current_approach"]["state"]["status"]
                    .as_str()
                    .unwrap_or("sequence"),
                p["current_approach"]["reason"]
                    .as_str()
                    .unwrap_or("See Policy and History for execution evidence")
            )
        },
        13.,
        MUTED,
    );
    title(panel, "PERSONALITY");
    text(
        panel,
        format!(
            "Caution {}   Empathy {}   Introspection {}",
            number(&p["personality"]["caution"]),
            number(&p["personality"]["empathy"]),
            number(&p["personality"]["introspection"])
        ),
        13.,
        INK,
    );
    title(panel, "BELIEFS — MAY BE WRONG");
    if let Some(beliefs) = p["beliefs"].as_array() {
        if beliefs.is_empty() {
            text(panel, "No retained claims yet.", 13., MUTED);
        }
        for belief in beliefs.iter().take(3) {
            text(
                panel,
                format!(
                    "Location {} · confidence {}\n{}\nsource #{}",
                    number(&belief["claim"]["location"]),
                    number(&belief["confidence"]),
                    belief["claim"]["text"].as_str().unwrap_or(""),
                    number(&belief["source"])
                ),
                13.,
                INK,
            );
        }
    }
}
fn describe(node: &Value) -> String {
    match node["kind"].as_str().unwrap_or("") {
        "priority" => "PRIORITY · recheck in order".into(),
        "sequence" => "SEQUENCE · remembers progress".into(),
        "guard" => format!("IF {}", condition(&node["condition"])),
        "action" => {
            let a = &node["action"];
            format!(
                "{}{}",
                a["skill"].as_str().unwrap_or("skill").to_uppercase(),
                if let Some(x) = a["destination"].as_i64() {
                    format!(" → {x}")
                } else if let Some(t) = a["text"].as_str() {
                    format!(" “{}”", t.chars().take(45).collect::<String>())
                } else {
                    String::new()
                }
            )
        }
        "reconsider" => "RECONSIDER · asynchronous".into(),
        _ => "Node".into(),
    }
}
fn condition(c: &Value) -> String {
    match c["kind"].as_str().unwrap_or("") {
        "danger" => format!(
            "danger believed at {}",
            c["location"]
                .as_i64()
                .map(|n| n.to_string())
                .unwrap_or("current place".into())
        ),
        "resource" => format!(
            "{} {} {}",
            c["resource"].as_str().unwrap_or(""),
            c["comparison"].as_str().unwrap_or(""),
            number(&c["value"])
        ),
        "at" => format!("at {}", number(&c["location"])),
        "food_at" => format!("remembered food at {}", number(&c["location"])),
        "not" => format!("not ({})", condition(&c["condition"])),
        "all" | "any" => {
            let sep = if c["kind"] == "all" { " & " } else { " | " };
            c["conditions"]
                .as_array()
                .map(|a| a.iter().map(condition).collect::<Vec<_>>().join(sep))
                .unwrap_or_default()
        }
        _ => c.to_string(),
    }
}
fn outline(node: &Value, path: String, depth: usize, rows: &mut Vec<(String, usize, String)>) {
    rows.push((path.clone(), depth, describe(node)));
    if let Some(children) = node["children"].as_array() {
        for (i, child) in children.iter().enumerate() {
            outline(child, format!("{path}/{i}"), depth + 1, rows);
        }
    }
    if let Some(child) = node.get("child") {
        outline(child, format!("{path}/guard"), depth + 1, rows);
    }
}
fn tree(panel: &mut ChildSpawnerCommands, p: &Value, game: &Game) {
    let approach = &p["current_approach"];
    let policy = &approach["policy"];
    if policy.is_null() {
        text(
            panel,
            "No persistent policy installed. Bootstrap / legacy actions are not generated reactive intelligence.",
            14.,
            MUTED,
        );
        return;
    }
    text(
        panel,
        format!(
            "Decision #{} · {}\nActive: {}\nCursors: {}",
            number(&approach["decision"]),
            approach["state"]["status"].as_str().unwrap_or(""),
            approach["state"]["active_path"]
                .as_str()
                .unwrap_or("between actions"),
            approach["state"]["cursors"]
        ),
        12.,
        MUTED,
    );
    let mut rows = vec![];
    outline(policy, "root".into(), 0, &mut rows);
    let active = approach["state"]["active_path"].as_str().unwrap_or("");
    for (path, depth, label) in rows.iter().skip(game.page * 4).take(4) {
        let selected = path == active
            || approach["state"]["branches"]
                .as_object()
                .is_some_and(|branches| {
                    branches.iter().any(|(root, index)| {
                        path == &format!("{root}/{}", index.as_u64().unwrap_or(0))
                    })
                });
        panel
            .spawn((
                Node {
                    margin: UiRect::left(px((*depth as f32 * 12.).min(70.))),
                    padding: UiRect::all(px(7)),
                    width: percent(100),
                    ..column()
                },
                BackgroundColor(if selected {
                    Color::srgb(0.24, 0.35, 0.20)
                } else {
                    Color::srgb(0.10, 0.16, 0.17)
                }),
            ))
            .with_children(|p| {
                text(
                    p,
                    format!("{}{label}", if selected { "▶ " } else { "" }),
                    12.,
                    INK,
                );
                text(p, path, 10., MUTED);
            });
    }
    panel.spawn(row()).with_children(|p| {
        button(p, "‹", Click::Prev, false);
        text(
            p,
            format!("{} nodes · page {}", rows.len(), game.page + 1),
            12.,
            MUTED,
        );
        button(p, "›", Click::Next, false);
    });
}
fn history(panel: &mut ChildSpawnerCommands, game: &Game) {
    let events = game.snapshot["events"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    if let Some(id) = game.event {
        if let Some(e) = events.iter().find(|e| e["id"] == id) {
            title(panel, "SELECTED CAUSAL EVENT");
            text(
                panel,
                format!(
                    "#{} · tick {} · {}",
                    number(&e["id"]),
                    number(&e["tick"]),
                    e["kind"].as_str().unwrap_or("")
                ),
                14.,
                INK,
            );
            let detail = serde_json::to_string_pretty(&e["data"]).unwrap_or_default();
            text(
                panel,
                detail.chars().take(650).collect::<String>(),
                12.,
                MUTED,
            );
            panel.spawn(row()).with_children(|p| {
                if let Some(parents) = e["parents"].as_array() {
                    for parent in parents.iter().take(4) {
                        if let Some(id) = parent.as_u64() {
                            button(p, format!("parent #{id}"), Click::Event(id), false);
                        }
                    }
                }
            });
        }
    }
    title(
        panel,
        if game.observer() {
            "RECENT HISTORY · SELECT TO INSPECT"
        } else {
            "YOUR PERCEPTIONS"
        },
    );
    for e in events
        .iter()
        .rev()
        .filter(|e| e["actor"] == game.selected || e["actor"].is_null())
        .skip(game.page * 5)
        .take(5)
    {
        if let Some(id) = e["id"].as_u64() {
            button(
                panel,
                format!(
                    "#{id}  t{}  {}",
                    number(&e["tick"]),
                    e["kind"].as_str().unwrap_or("")
                ),
                Click::Event(id),
                game.event == Some(id),
            );
        }
    }
    panel.spawn(row()).with_children(|p| {
        button(p, "Newer", Click::Prev, false);
        button(p, "Older", Click::Next, false);
    });
}
pub fn interact(
    query: Query<(&Interaction, &Click), Changed<Interaction>>,
    mut game: ResMut<Game>,
    mut net: NonSendMut<Network>,
) {
    for (interaction, action) in &query {
        if *interaction != Interaction::Pressed {
            continue;
        }
        match action {
            Click::Select(id) => {
                game.scroll[1] = 0.;
                game.selected = *id;
                game.page = 0;
                game.event = None;
            }
            Click::Tab(tab) => {
                game.scroll[1] = 0.;
                game.tab = *tab;
                game.page = 0;
                game.event = None;
            }
            Click::Mode => {
                net.post("mode", "/api/mode", json!({"observer":!game.observer()}));
                game.typing = false;
                game.status = "Changing server-granted role…".into();
            }
            Click::Step => net.control("step"),
            Click::Play => net.control(if game.snapshot["paused"] == true {
                "resume"
            } else {
                "pause"
            }),
            Click::New => net.post("new", "/api/new-run", json!({})),
            Click::Archive => net.post("archive", "/api/archive", json!({})),
            Click::Live => {
                game.status = "Returned to live authoritative run".into();
                game.archive = false;
                net.latest.clear();
                game.page = 0;
            }
            Click::Left | Click::Right => {
                net.intent(json!({"skill":"move","destination":(game.own_position()+if matches!(action,Click::Left){-1}else{1}).clamp(-10,10),"duration":1}));
            }
            Click::Gather => net.intent(json!({"skill":"gather","duration":1})),
            Click::Eat => net.intent(json!({"skill":"eat","duration":1})),
            Click::Rest => net.intent(json!({"skill":"rest","duration":3})),
            Click::Speak => game.typing = true,
            Click::Prev => game.page = game.page.saturating_sub(1),
            Click::Next => game.page = (game.page + 1).min(30),
            Click::Event(id) => {
                game.event = Some(*id);
                game.scroll[1] = 0.;
            }
            Click::Reconnect => {
                if let Some(c) = net.connection.take() {
                    let _ = c.disconnect();
                }
                net.connecting = true;
                net.post("boot", "/api/session", json!({}));
            }
        }
        game.dirty = true;
    }
}

pub fn scroll(
    mut wheel: MessageReader<bevy::input::mouse::MouseWheel>,
    window: Single<&Window>,
    mut panels: Query<(&Panel, &mut ScrollPosition)>,
    mut game: ResMut<Game>,
) {
    for event in wheel.read() {
        let Some(pos) = window.cursor_position() else {
            continue;
        };
        let index = if pos.x < 246. {
            0
        } else if pos.x > window.width() - 430. {
            1
        } else {
            continue;
        };
        for (panel, mut offset) in &mut panels {
            if panel.0 == index {
                let delta = match event.unit {
                    bevy::input::mouse::MouseScrollUnit::Line => event.y * 24.,
                    _ => event.y,
                };
                offset.y = (offset.y - delta).max(0.);
                game.scroll[index] = offset.y;
            }
        }
    }
}
