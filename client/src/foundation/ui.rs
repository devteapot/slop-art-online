use super::*;
use spacetimedb_sdk::DbContext;
#[derive(Component)]
pub(super) struct UiRoot;
#[derive(Component)]
pub struct Panel(usize);
#[derive(Component, Clone)]
pub enum Click {
    Select(u64),
    Arena(Option<String>),
    Tab(usize),
    Mode,
    Step,
    Play,
    New,
    Archive,
    Live,
    Gather,
    Eat,
    Rest,
    Intent(Value),
    Speak,
    Prev,
    Next,
    Event(u64),
    Reconnect,
    Inspect,
    World,
    Overlays,
    Sessions,
    Focus(String),
    Follow,
    Detach,
}
const INK: Color = Color::srgb(0.86, 0.91, 0.86);
const MUTED: Color = Color::srgb(0.55, 0.65, 0.62);
const PANEL: Color = Color::srgba(0.045, 0.085, 0.09, 0.94);
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
    #[cfg(target_arch = "wasm32")]
    if web_sys::window()
        .and_then(|w| w.location().hash().ok())
        .is_some_and(|h| h == "#inspect")
    {
        game.world_visible = false;
        game.inspect = true;
        game.sessions_open = true;
    }
    #[cfg(not(target_arch = "wasm32"))]
    if std::env::var("BEVY_INSPECT").as_deref() == Ok("1") {
        game.world_visible = false;
        game.inspect = true;
        game.sessions_open = true;
    }
    game.dirty = true;
}
// Share panel bounds with world picking and wheel handling; hidden panels never capture input.
pub fn captures(game: &Game, pos: Vec2, width: f32, height: f32) -> bool {
    if game.compact { return game.inspect && pos.x > width-428.; }
    pos.y < 92.
        || pos.y > height - 112.
        || (game.sessions_open && pos.x < 258.)
        || (game.inspect && pos.x > width - 430.)
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
        "ARCHIVE · read-only model evidence"
    } else if mode == "live_fixture" {
        "LIVE · authored fixture · no inference"
    } else if mode == "live_model" {
        "LIVE · configured model reasoning"
    } else {
        "CONNECTING"
    };
    commands.spawn((UiRoot, GlobalZIndex(10), Node {position_type:PositionType::Absolute,width:percent(100),height:percent(100),..default()})).with_children(|root| {
        if !game.compact {
        root.spawn((Node {position_type:PositionType::Absolute,left:px(12),right:px(12),top:px(12),height:px(70),padding:UiRect::all(px(12)),justify_content:JustifyContent::SpaceBetween,..row()},BackgroundColor(PANEL))).with_children(|bar| {
            bar.spawn(column()).with_children(|p| {text(p,"S A O  /  BEHAVIOR LAB",20.,INK);text(p,evidence,12.,MUTED);});
            bar.spawn(row()).with_children(|p| {
                button(p,if game.snapshot["arenas"].is_array(){"Arenas / sessions"}else{"Sessions"},Click::Sessions,game.sessions_open);
                button(p,if game.world_visible {"Close world"} else {"Peek into world"},Click::World,game.world_visible);
                button(p,"Inspect [I]",Click::Inspect,game.inspect);
                button(p,"Labels [O]",Click::Overlays,game.overlays);
                if !game.archive {button(p,"Detach",Click::Detach,false);}
            });
        });
        }
        if game.sessions_open && !game.compact {
            root.spawn((Node{position_type:PositionType::Absolute,left:px(12),top:px(92),bottom:px(112),width:px(234),padding:UiRect::all(px(14)),overflow:Overflow::scroll_y(),..column()},BackgroundColor(PANEL),Panel(0),ScrollPosition(Vec2::new(0.,game.scroll[0])))).with_children(|left| {
                if let Some(arenas)=game.snapshot["arenas"].as_array().filter(|a| !a.is_empty()) {
                    title(left,"WORLD AREAS");
                    text(left,"Areas share this session's clock. Select an area to focus the map.",12.,MUTED);
                    button(left,"Whole world",Click::Arena(None),game.arena.is_none());
                    for arena in arenas {
                        let id=arena["id"].as_str().unwrap_or("");
                        button(left,arena["label"].as_str().unwrap_or(id),Click::Arena(Some(id.into())),game.arena.as_deref()==Some(id));
                    }
                }
                title(left,"HOSTED SESSIONS");
                text(left,"Focus changes this view. Other worlds keep their own clocks.",12.,MUTED);
                for run in &game.runs {
                    if let Some(id)=run["run"].as_str() {
                        button(left,format!("{}\ntick {} · {}",id.trim_start_matches("sim-bevy-"),number(&run["tick"]),if run["stopped"]==true {"finished"} else if run["paused"]==true {"paused"} else if run["paused"]==false {"running"} else {"clock unknown"}),Click::Focus(id.into()),game.snapshot["run"]==id && !game.archive);
                    }
                }
                if game.observer() && !game.archive {if !game.snapshot["arenas"].is_array(){button(left,"New parallel session",Click::New,false);}button(left,"Recorded model policy",Click::Archive,false);}
                if game.archive {button(left,"Back to live session",Click::Live,false);}
                title(left,"CHARACTERS");
                if let Some(players)=game.snapshot["players"].as_array() {
                    for player in players {
                        let id=player["id"].as_u64().unwrap_or(0);
                        let arena=game.snapshot["arenas"].as_array().and_then(|a|a.iter().find(|a|a["actors"].as_array().is_some_and(|ids|ids.contains(&json!(id)))));
                        if game.arena.as_ref().is_some_and(|selected|arena.is_none_or(|a|a["id"]!=*selected)){continue;}
                        let name=player["name"].as_str().unwrap_or("Character");
                        button(left,format!("{name} #{id} · {}",player["runtime"].as_str().unwrap_or("character")),Click::Select(id),id==game.selected);
                    }
                }
                if !game.archive && game.snapshot["can_participate"] != false {button(left,if game.observer(){"Participate as You"}else{"Return to observer"},Click::Mode,false);}
                button(left,"Reconnect",Click::Reconnect,false);
            });
        }
        if game.inspect {
            root.spawn((Node{position_type:PositionType::Absolute,right:px(12),top:px(92),bottom:px(112),width:px(404),padding:UiRect::all(px(16)),overflow:Overflow::scroll_y(),..column()},BackgroundColor(PANEL),Panel(1),ScrollPosition(Vec2::new(0.,game.scroll[1])))).with_children(|panel| {
                text(panel,p["name"].as_str().unwrap_or("Select a character in the world"),24.,INK);
                if let Some(arena)=p["arena"].as_str() {text(panel,format!("{arena} · {}",p["runtime"].as_str().unwrap_or("")),12.,MUTED);}
                text(panel,if game.observer(){"Observer truth / individual understanding"}else{"Your perceptions / private understanding"},12.,MUTED);
                panel.spawn(row()).with_children(|p| {button(p,"Mind",Click::Tab(0),game.tab==0);button(p,"Policy",Click::Tab(1),game.tab==1);button(p,"History",Click::Tab(2),game.tab==2);button(p,"Knowledge",Click::Tab(3),game.tab==3);button(p,"Life",Click::Tab(4),game.tab==4);});
                match game.tab {0=>mind(panel,&p),1=>tree(panel,&p,&game),3=>knowledge(panel,&p,&game),4=>life(panel,&p,&game),_=>history(panel,&game)}
            });
        }
        if !game.world_visible {
            root.spawn(Node{position_type:PositionType::Absolute,left:px(280),top:percent(40),width:px(320),..column()}).with_children(|p| {
                text(p,"World view detached",24.,INK);
                text(p,"The session continues on the server. Choose a session to inspect, or peek into its world whenever you want.",16.,MUTED);
            });
        }
        if !game.compact {
        root.spawn((Node{position_type:PositionType::Absolute,left:px(12),right:px(12),bottom:px(12),height:px(88),padding:UiRect::axes(px(16),px(8)),..column()},BackgroundColor(PANEL))).with_children(|bottom| {
            bottom.spawn(row()).with_children(|p| {
                text(p,format!("{:.1}s / {:.0}s · {}",game.snapshot["time_ms"].as_u64().unwrap_or(game.snapshot["tick"].as_u64().unwrap_or(0) * 2500) as f64 / 1000.,game.snapshot["max_ticks"].as_u64().unwrap_or(0) as f64 * 2.5,if game.snapshot["stopped"]==true{"FINISHED"}else if game.snapshot["paused"]==true{"PAUSED"}else{"RUNNING"}),15.,INK);
                if game.observer() && !game.archive {button(p,"Step",Click::Step,false);button(p,if game.snapshot["paused"]==true{"Resume"}else{"Pause"},Click::Play,false);}
                if !game.observer() && !game.archive && !game.snapshot.is_null() {
                    button(p,"Gather",Click::Gather,false);button(p,"Eat",Click::Eat,false);button(p,"Rest",Click::Rest,false);button(p,"Speak",Click::Speak,game.typing);
                }
                button(p,"Follow [F]",Click::Follow,game.follow);
                text(p,"WASD / right drag pan · wheel zoom",12.,MUTED);
            });
            text(bottom,if game.typing{format!("Say: {} | Enter to send",game.draft)}else{format!("{} · {}",game.snapshot["run"].as_str().unwrap_or("Connecting"),game.status)},12.,MUTED);
        });
        }
    });
}
fn mind(panel: &mut ChildSpawnerCommands, p: &Value) {
    for membership in p["society"]["initial_memberships"].as_array().into_iter().flatten() {
        text(panel, format!("Initial affiliation: {}", membership["label"].as_str().unwrap_or("")), 12., MUTED);
    }
    for office in p["society"]["initial_offices"].as_array().into_iter().flatten() {
        text(panel, format!("Initial office: {}", office["label"].as_str().unwrap_or("")), 12., MUTED);
    }
    title(panel, "MOTIVE");
    text(
        panel,
        p["motive"]
            .as_str()
            .unwrap_or("This character's private mind is not visible in participant mode."),
        14.,
        INK,
    );
    if let Some(goal) = p["current_goal"].as_str() {
        title(panel, "CURRENT GOAL");
        text(panel, goal, 14., INK);
    }
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
    if let Some(habit) = p.get("starting_behavior").filter(|v| v.is_object()) {
        text(panel, format!("Started with {} · revision {}\n{}",
            habit["id"].as_str().unwrap_or("a seed habit"), number(&habit["revision"]),
            habit["description"].as_str().unwrap_or("This initial habit can change through experience.")), 12., MUTED);
    }
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
    if let Some(activity) = p.get("recent_activity").filter(|a| a.is_object()) {
        title(panel, "RECENT ACTIVITY");
        text(panel, format!("{} position changes · {} moves without displacement", number(&activity["position_changes"]), number(&activity["completed_moves_without_displacement"])), 12., MUTED);
        for site in activity["own_site_food_changes"].as_array().into_iter().flatten().take(3) {
            text(panel, format!("Cell {}: withdrew {}, deposited {} · net {}", number(&site["location"]), number(&site["withdrawn"]), number(&site["deposited"]), number(&site["net_added"])), 12., INK);
        }
    }
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
fn life(panel: &mut ChildSpawnerCommands, p: &Value, game: &Game) {
    utilities(panel, p, game);
    let development=&p["development"];
    let local=&p["local_lifecycle"];
    let own=!game.observer() && !game.archive && game.snapshot["actor"]==p["id"];
    let dependent=development["dependent"]==true;
    title(panel,"BODY AND DEVELOPMENT");
    text(panel,format!("{} · {}",development["body"].as_str().unwrap_or("unobserved body"),
        if dependent {"dependent"} else {"self-supporting"}),14.,INK);
    if dependent {
        let age=game.snapshot["time_ms"].as_u64().unwrap_or(0).saturating_sub(development["born_ms"].as_u64().unwrap_or(0));
        text(panel,format!("Age {}s · {} care meals · {} guided practices",age/1000,
            number(&development["care_meals"]),number(&development["practice"])),12.,MUTED);
        text(panel,"Food, actual care and learning support development. Receiving a report alone does not grant independent provisioning.",12.,MUTED);
    }
    if local.is_null() {
        text(panel,"No local population facilities or observations are available.",13.,MUTED);
        return;
    }
    title(panel,"LOCAL PEOPLE");
    for person in local["people"].as_array().into_iter().flatten() {
        if person["id"]==p["id"] {continue;}
        let name=person["name"].as_str().unwrap_or("neighbor");
        text(panel,format!("{} · {}",name,if person["dependent"]==true {
            if person["needs_care"]==true {"dependent, needs a meal"} else {"dependent, fed for now"}
        } else {"self-supporting"}),13.,INK);
        if own && !dependent && person["dependent"]==true && person["needs_care"]==true {
            button(panel,format!("Care for {name}"),Click::Intent(json!({"skill":"care","target":person["id"],"duration":1})),false);
        }
        if own && !dependent && development["body"]=="biological" && person["body"]=="biological" && person["dependent"]!=true {
            button(panel,format!("Offer reproduction to {name}"),Click::Intent(json!({"skill":"offer_reproduction","target":person["id"],"duration":1})),false);
            let mutual=local["own_offer"]["partner"]==person["id"] && local["offers_to_you"].as_array().into_iter().flatten().any(|o|o["actor"]==person["id"]);
            if mutual {button(panel,format!("Reproduce with {name}"),Click::Intent(json!({"skill":"reproduce","target":person["id"],"duration":1})),false);}
        }
    }
    if own && local["own_offer"].is_object() {
        button(panel,"Withdraw my reproduction offer",Click::Intent(json!({"skill":"withdraw_reproduction","duration":1})),false);
    }
    if local["workshop"]==true {
        title(panel,"WORKSHOP");
        text(panel,"Create a dependent artificial body: 6 carried food as material, 30 energy, 45 seconds. This body still needs food, support and learning.",12.,MUTED);
        if own && !dependent {button(panel,"Fabricate a new individual",Click::Intent(json!({"skill":"fabricate","duration":1})),false);}
    }
    if own && dependent {
        title(panel,"GUIDED PRACTICE");
        for holding in p["knowledge"].as_array().into_iter().flatten().filter(|h|h["interpretation"].is_string() && h["record"]["location"]==p["position"]) {
            for care in development["care"].as_array().into_iter().flatten() {
                if local["people"].as_array().into_iter().flatten().any(|q|q["id"]==care["caregiver"] && q["dependent"]!=true) {
                    button(panel,format!("Practice {} with #{}",holding["record"]["topic"].as_str().unwrap_or("gathering"),number(&care["caregiver"])),
                        Click::Intent(json!({"skill":"practice","target":care["caregiver"],"record":holding["record"]["id"],"duration":1})),false);
                }
            }
        }
    }
}
fn utilities(panel: &mut ChildSpawnerCommands, p: &Value, game: &Game) {
    let utility=&p["infrastructure"];
    if utility["enabled"]!=true {return;}
    let own=!game.observer() && !game.archive && game.snapshot["actor"]==p["id"];
    title(panel,"POWER AND MATERIALS");
    if p["body"]["support"]=="electric" {
        text(panel,format!("Battery {} / {} · stamina {}",number(&p["body"]["charge"]),number(&p["body"]["capacity"]),number(&p["energy"])),14.,INK);
        text(panel,"This body needs electricity. Rest restores stamina; charging replenishes its battery.",12.,MUTED);
    }
    text(panel,format!("Carried parts {} · cooling water {}",number(&utility["materials"]["parts"]),number(&utility["materials"]["water"])),13.,INK);
    for station in utility["stations"].as_array().into_iter().flatten() {
        let id=station["id"].clone();
        text(panel,station["label"].as_str().unwrap_or("Utility station"),15.,INK);
        text(panel,format!("Power {} / {} · condition {} · {}",number(&station["electricity"]),number(&station["electricity_capacity"]),number(&station["integrity"]),if station["enabled"]==true {"enabled"} else {"disabled"}),12.,MUTED);
        text(panel,format!("Parts {} · water {} · queued jobs {}",number(&station["materials"]["parts"]),number(&station["materials"]["water"]),number(&station["queue_length"])),12.,MUTED);
        if own && station["rights"]["use_allowed"]==true {
            if p["body"]["support"]=="electric" {
                let room=p["body"]["capacity"].as_i64().unwrap_or(0)-p["body"]["charge"].as_i64().unwrap_or(0);
                let amount=room.min(20).max(0);
                if amount>0 {button(panel,format!("Charge {amount}"),Click::Intent(json!({"skill":"infrastructure","infrastructure":{"op":"charge","station":id,"amount":amount}})),false);}
            }
            if station["materials"]["water"].as_i64().unwrap_or(0)>0 {
                button(panel,"Collect one water",Click::Intent(json!({"skill":"infrastructure","infrastructure":{"op":"take_material","station":id,"material":"water","amount":1}})),false);
            }
        }
        if own && station["rights"]["maintain"]==true && utility["materials"]["water"].as_i64().unwrap_or(0)>0 {
            button(panel,"Supply one cooling water",Click::Intent(json!({"skill":"infrastructure","infrastructure":{"op":"deposit_material","station":id,"material":"water","amount":1}})),false);
        }
        for job in station["own_jobs"].as_array().into_iter().flatten() {
            text(panel,format!("Your job #{} · {}/{} work",number(&job["id"]),number(&job["progress"]),number(&job["required"])),12.,INK);
            if let Some(reason)=job["blocked_reason"].as_str() {text(panel,reason,12.,MUTED);}
            if own && job["report"].is_string() && job["retrieved"]!=true {
                button(panel,"Collect computed report",Click::Intent(json!({"skill":"infrastructure","infrastructure":{"op":"retrieve_job","station":id,"job":job["id"]}})),false);
            }
        }
    }
}
fn law_scope_name(scope: &Value) -> String {
    if scope["kind"] == "universal" { "Universal".into() }
    else { format!("Territory {}", scope["region"].as_str().unwrap_or("unknown")) }
}
fn law_terminal(p: &Value) -> Option<&Value> {
    if p["health"].as_i64().unwrap_or(0) <= 0 || p["infrastructure"]["enabled"] != true { return None; }
    p["infrastructure"]["stations"].as_array()?.iter().find(|s|
        s["position"] == p["position"] && s["enabled"] == true && s["integrity"].as_i64().unwrap_or(0) > 0
        && s["rights"]["use_allowed"] == true
        && s["modules"].as_array().is_some_and(|m| m.iter().any(|m| m == "terminal")))
}
fn inspected_law_source<'a>(p: &'a Value, record: Option<&Value>, installed: Option<&Value>) -> Option<&'a str> {
    p["memories"].as_array()?.iter().rev().find(|m| {
        if m["kind"] != "law_inspected" { return false; }
        let content = &m["content"];
        record.is_some_and(|r| content["record"] == r["id"]
            && content["law_program"]["source_hash"] == r["law_program"]["source_hash"])
            || installed.is_some_and(|r| content["installed"]["scope"] == r["scope"]
                && content["installed"]["revision"] == r["revision"])
    }).and_then(|m| m["content"]["law_program"]["source"].as_str())
}
fn laws(panel: &mut ChildSpawnerCommands, p: &Value, game: &Game) {
    let laws = &p["laws"];
    if !laws.is_object() { return; }
    let own = !game.observer() && !game.archive && game.snapshot["actor"] == p["id"];
    title(panel, "CURRENT LAWS");
    text(panel, format!("Base law revision {}", number(&laws["effective_binding"]["base"]["revision"])), 12., MUTED);
    text(panel, format!("Effective binding {}", laws["effective_binding"]["digest"].as_str().unwrap_or("unknown")), 11., MUTED);
    for scope in laws["scopes"].as_array().into_iter().flatten() {
        text(panel, format!("{} · revision {}", law_scope_name(&scope["scope"]), number(&scope["revision"])), 13., INK);
        if scope["scope"]["kind"] == "territory" {
            text(panel, if scope["local_grant"] == true { "Initial local editing grant here: yes" } else { "Initial local editing grant here: no" }, 12., MUTED);
        }
        text(panel, format!("Scope binding {}", scope["binding"].as_str().unwrap_or("unknown")), 11., MUTED);
        if scope["revision"].as_u64().unwrap_or(0) == 0 {
            text(panel, "No installed override in this scope.", 12., MUTED);
            continue;
        }
        if own {
            if let Some(station) = law_terminal(p) {
                button(panel, format!("Inspect installed {} law", law_scope_name(&scope["scope"])),
                    Click::Intent(json!({"skill":"infrastructure","duration":1,"infrastructure":{"op":"inspect_installed_law","station":station["id"],"scope":scope["scope"]}})), false);
            }
        }
        if let Some(source) = inspected_law_source(p, None, Some(scope)) {
            text(panel, "Last personally inspected source for this revision", 11., MUTED);
            text(panel, source, 12., INK);
        }
    }
}
fn knowledge(panel: &mut ChildSpawnerCommands, p: &Value, game: &Game) {
    let own = !game.observer() && !game.archive && game.snapshot["actor"] == p["id"];
    if p["infrastructure"]["enabled"]==true {
        title(panel,"TECHNIQUES AND EXPERIMENTS");
        text(panel,if p["research"]["can_author"]==true {"This person can currently author a technique."} else {"Authorship capability has not been demonstrated under the current rules."},12.,MUTED);
        text(panel,"A code copy and an experiment report are separate records. Receiving code does not grant the sender's practical capability.",12.,MUTED);
    }
    laws(panel, p, game);
    title(panel, "PERSONAL RECORDS");
    text(panel, "Reports can disagree. Reading preserves a copy; understanding and practical ability develop separately.", 12., MUTED);
    if let Some(holdings) = p["knowledge"].as_array() {
        if holdings.is_empty() { text(panel, "No records held.", 13., MUTED); }
        for holding in holdings {
            let record = &holding["record"];
            title(panel, record["topic"].as_str().unwrap_or("Record"));
            text(panel, record["text"].as_str().unwrap_or(""), 13., INK);
            text(panel, format!("{} · author #{} · stated confidence {}", record["id"].as_str().unwrap_or(""),number(&record["author"]),number(&record["confidence"])), 11., MUTED);
            text(panel, holding["interpretation"].as_str().unwrap_or("Not yet assessed by this person."), 12., MUTED);
            if let Some(program)=record.get("program").filter(|v|v.is_object()) {
                let can_run=p["research"]["programs"].as_array().into_iter().flatten().any(|v|v["record"]==record["id"] && v["can_run"]==true);
                text(panel,if can_run {"Technique use is currently permitted."} else {"Technique use is not currently permitted."},12.,MUTED);
                text(panel,format!("Inputs: {}\nOutputs: {}",program["input_contract"].as_str().unwrap_or(""),program["output_contract"].as_str().unwrap_or("")),12.,INK);
                if own {
                    if let Some(station)=p["infrastructure"]["stations"].as_array().into_iter().flatten().find(|s|
                        s["position"]==p["position"] && s["enabled"]==true && s["rights"]["use_allowed"]==true && s["modules"].as_array().is_some_and(|m|m.iter().any(|m|m=="terminal"))) {
                        button(panel,"Inspect code",Click::Intent(json!({"skill":"infrastructure","infrastructure":{"op":"inspect_program","station":station["id"],"record":record["id"]}})),false);
                    }
                }
                if let Some(source)=p["memories"].as_array().into_iter().flatten().rev().find(|m|
                    m["kind"]=="program_inspected" && m["content"]["record"]==record["id"] && m["content"]["program"]["source_hash"]==program["source_hash"])
                    .and_then(|m|m["content"]["program"]["source"].as_str()) {
                    text(panel,"Last personally inspected source",11.,MUTED);
                    text(panel,source,12.,INK);
                }
            }
            if let Some(experiment)=record.get("experiment").filter(|v|v.is_object()) {
                text(panel,format!("{} experiment · {} paid work units · {}",experiment["kind"].as_str().unwrap_or("terminal"),number(&experiment["paid_quanta"]),if experiment["successful"]==true {"successful on supplied inputs"} else {"unsuccessful on supplied inputs"}),12.,MUTED);
                if experiment["output"].is_array() {text(panel,format!("Recorded output: {}",experiment["output"]),12.,INK);}
            }
            if let Some(program) = record.get("law_program").filter(|v| v.is_object()) {
                let hooks = program["hooks"].as_array().into_iter().flatten().filter_map(Value::as_str).collect::<Vec<_>>().join(", ");
                text(panel, format!("Law code · hooks: {hooks}"), 12., INK);
                text(panel, format!("Source {}", program["source_hash"].as_str().unwrap_or("unknown")), 11., MUTED);
                if own {
                    if let Some(station) = law_terminal(p) {
                        button(panel, "Inspect law code", Click::Intent(json!({"skill":"infrastructure","duration":1,"infrastructure":{"op":"inspect_law","station":station["id"],"record":record["id"]}})), false);
                    }
                }
                if let Some(source) = inspected_law_source(p, Some(record), None) {
                    text(panel, "Last personally inspected law source", 11., MUTED);
                    text(panel, source, 12., INK);
                }
            }
            if let Some(experiment) = record.get("law_experiment").filter(|v| v.is_object()) {
                text(panel, format!("Law experiment · paid by #{} · {} work units · {}", number(&experiment["operator"]), number(&experiment["paid_quanta"]),
                    if experiment["successful"] == true { "predictions matched" } else { "predictions did not all match" }), 12., MUTED);
                text(panel, format!("{} · {} supplied cases", law_scope_name(&experiment["scope"]), experiment["cases"].as_array().map_or(0, Vec::len)), 12., INK);
                text(panel, format!("Tested source {}\nTested binding {}", experiment["program_hash"].as_str().unwrap_or("unknown"), experiment["binding"]["digest"].as_str().unwrap_or("unknown")), 11., MUTED);
                let current = p["laws"]["scopes"].as_array().into_iter().flatten().any(|s| s["scope"] == experiment["scope"] && s["binding"] == experiment["binding"]["digest"]);
                text(panel, if current { "The experiment names the current scope binding." } else { "This experiment names a different or unavailable scope binding." }, 12., MUTED);
            }
            if own {
                if p["health"].as_i64().unwrap_or(0) > 0 && p["energy"].as_i64().unwrap_or(0) >= 1 {
                    button(panel, "Reread record", Click::Intent(json!({"skill":"reread_record","record":record["id"],"duration":1})), false);
                }
                for other in game.snapshot["players"].as_array().into_iter().flatten().filter(|v|v["id"]!=p["id"] && v["position"]==p["position"]) {
                    button(panel,format!("Teach {}",other["name"].as_str().unwrap_or("neighbor")),Click::Intent(json!({"skill":"teach","target":other["id"],"record":record["id"],"duration":1})),false);
                }
                for archive in game.snapshot["archives"].as_array().into_iter().flatten().filter(|a|a["position"]==p["position"] && a["destroyed"]!=true) {
                    if !archive["records"].as_array().into_iter().flatten().any(|r|r["id"]==record["id"]) {
                        button(panel,format!("Record in {}",archive["label"].as_str().unwrap_or("archive")),Click::Intent(json!({"skill":"record","archive":archive["id"],"record":record["id"],"duration":1})),false);
                    }
                }
            }
        }
    } else { text(panel, "This person's private records are not visible.", 13., MUTED); }
    title(panel, if game.observer() { "PHYSICAL ARCHIVES" } else { "KNOWN ARCHIVES" });
    for archive in game.snapshot["archives"].as_array().into_iter().flatten() {
        title(panel, archive["label"].as_str().unwrap_or("Archive"));
        text(panel,format!("Cell {} · {}",number(&archive["position"]),if archive["destroyed"]==true {"destroyed"} else {"intact"}),12.,MUTED);
        for record in archive["records"].as_array().into_iter().flatten() {
            text(panel,record["topic"].as_str().unwrap_or("Record"),13.,INK);
            if game.observer() { text(panel,record["text"].as_str().unwrap_or(""),12.,MUTED); }
            if own && archive["position"]==p["position"] && archive["destroyed"]!=true {
                button(panel,"Consult record",Click::Intent(json!({"skill":"consult","archive":archive["id"],"record":record["id"],"duration":1})),false);
            }
        }
        if own && archive["position"]==p["position"] && archive["destroyed"]!=true {
            button(panel,"Destroy archive",Click::Intent(json!({"skill":"destroy_archive","archive":archive["id"],"duration":1})),false);
        }
    }
}
fn describe(node: &Value) -> String {
    match node["kind"].as_str().unwrap_or("") {
        "priority" => "PRIORITY · recheck in order".into(),
        "sequence" => "SEQUENCE · remembers progress".into(),
        "once" => "ONCE UNTIL SUCCESS".into(),
        "guard" => format!("WHILE {}", condition(&node["condition"])),
        "when" => format!("START WHEN {}", condition(&node["condition"])),
        "action" => {
            let a = &node["action"];
            format!(
                "{}{}",
                a["skill"].as_str().unwrap_or("skill").to_uppercase(),
                if let Some(x) = a["destination"].as_i64() {
                    format!(" → {x}")
                } else if let Some(t) = a["text"].as_str() {
                    format!(" “{}”", t.chars().take(45).collect::<String>())
                } else if a["record"].is_string() || a["archive"].is_number() {
                    format!(" {}{}",a["record"].as_str().unwrap_or(""),a["archive"].as_u64().map(|id|format!(" @ archive {id}")).unwrap_or_default())
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
        "has_knowledge" => format!("holds {}", c["record"].as_str().unwrap_or("record")),
        "needs_care" => format!("observed care need for #{}", number(&c["target"])),
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
        outline(child, format!("{path}/{}", if node["kind"] == "when" { "when" } else if node["kind"] == "once" { "once" } else { "guard" }), depth + 1, rows);
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
            Click::Arena(id) => {
                game.arena=id.clone(); game.frame=true; game.follow=false;
                if let Some(arena)=game.snapshot["arenas"].as_array().and_then(|a|a.iter().find(|a|Some(a["id"].as_str().unwrap_or(""))==id.as_deref())) {
                    game.selected=arena["actors"][0].as_u64().unwrap_or(1);
                }
                game.inspect=false; game.scroll[0]=0.;
            }
            Click::Select(id) => {
                game.scroll[1] = 0.;
                game.selected = *id;
                game.inspect = true;
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
            Click::Inspect => game.inspect = !game.inspect,
            Click::World => {
                game.world_visible = !game.world_visible;
                if !game.world_visible {
                    game.inspect = true;
                    game.sessions_open = true;
                }
            }
            Click::Overlays => game.overlays = !game.overlays,
            Click::Follow => game.follow = !game.follow,
            Click::Sessions => {
                game.sessions_open = !game.sessions_open;
                if game.sessions_open && game.observer() {
                    net.post("runs", "/api/runs", json!({}));
                }
            }
            Click::Focus(run) => {
                net.post("focus", "/api/focus", json!({"run":run}));
                game.status = "Focusing session…".into();
            }
            Click::Detach => {
                #[cfg(target_arch = "wasm32")]
                let opened = web_sys::window().is_some_and(|w| {
                    w.open_with_url_and_target(
                        &format!(
                            "/?run={}#inspect",
                            game.snapshot["run"].as_str().unwrap_or("")
                        ),
                        "sao-inspector",
                    )
                    .ok()
                    .flatten()
                    .is_some()
                });
                #[cfg(not(target_arch = "wasm32"))]
                let opened = std::env::current_exe().ok().is_some_and(|exe| {
                    std::process::Command::new(exe)
                        .env("BEVY_INSPECT", "1")
                        .env(
                            "BEVY_FOCUS_RUN",
                            game.snapshot["run"].as_str().unwrap_or(""),
                        )
                        .spawn()
                        .is_ok()
                });
                if opened {
                    game.inspect = false;
                } else {
                    game.status =
                        "Could not open inspector; allow popups for this site and try again".into();
                }
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
            Click::Gather => net.intent(json!({"skill":"gather","duration":1})),
            Click::Eat => net.intent(json!({"skill":"eat","duration":1})),
            Click::Rest => net.intent(json!({"skill":"rest","duration":3})),
            Click::Intent(action) => net.intent(action.clone()),
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
        let index = if game.sessions_open && pos.x < 258. {
            0
        } else if game.inspect && pos.x > window.width() - 430. {
            1
        } else {
            continue;
        };
        if pos.y < 92. || pos.y > window.height() - 112. {
            continue;
        }
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
