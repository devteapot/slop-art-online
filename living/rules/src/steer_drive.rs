// A player's walk keys and held look, replayed through the steering rules (`steer::plan`, the
// facing segments `steer::walk_facing` and `steer::stand_facing`) the way the authority's
// `motion` drives them for `human_move` and `human_face`: the same intent checks, brake and
// glide, resume and anchor, and steering updates at the first 60 Hz tick after they are due.
// What it leaves out: crowding (`separate`), roads, obstacles, breath and the input bucket. It is
// included by the steering tests and by the `face_replay` example (`include!`), with `geo` the
// steering module and `Map` the map type in scope; it is not a simulator of its own.

pub const IDLE: u64 = u64::MAX;
pub const TICK_MS: f64 = 1000.0 / 60.0;
pub const MIN_STEP_MS: u64 = 40;
pub const RESUME_MS: u64 = 40;

/// The laws and the body's motion as the shipped rules give them for a person.
#[derive(Clone, Copy, Debug)]
pub struct Laws {
    pub walk: f32,
    pub run: f32,
    pub steer_s: f32,
    pub limit: f32,
    pub slack: f32,
    pub tune: geo::Tuning,
}

impl Default for Laws {
    fn default() -> Self {
        Self { walk: 2.6, run: 1.65, steer_s: 2.0, limit: 75f32.to_radians(), slack: 10f32.to_radians(), tune: geo::Tuning { road_speed: 1.0, ..Default::default() } }
    }
}

#[derive(Clone, Copy, Debug, Default)]
pub struct Body {
    pub x: f32,
    pub y: f32,
    pub t_ms: u64,
    pub vx: f32,
    pub vy: f32,
    pub heading: f32,
    pub turn: f32,
    pub turn_s: f32,
    pub next_ms: u64,
    pub speed: f32,
    pub face_off: f32,
    pub face_turn: f32,
    pub face_turn_s: f32,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct Steer {
    pub walking: bool,
    pub gx: f32,
    pub gy: f32,
    pub run: bool,
    pub look_on: bool,
    pub look: f32,
}

/// One input: a `human_move` (`dir` None: stop) or a `human_face` (`look` None: release).
#[derive(Clone, Copy, Debug)]
pub enum Input {
    Move { dir: Option<(f32, f32)>, run: bool },
    Look { dir: Option<(f32, f32)> },
}

pub struct Drive {
    pub b: Body,
    pub st: Steer,
    pub laws: Laws,
    pub map: Map,
    /// Every row written: (when, the row).
    pub rows: Vec<(u64, Body)>,
}

fn speed_of(b: &Body) -> f32 {
    b.vx.hypot(b.vy)
}

fn moving(b: &Body) -> bool {
    b.vx != 0.0 || b.vy != 0.0
}

pub fn heading_at(b: &Body, now: u64) -> f32 {
    if b.turn == 0.0 || b.turn_s <= 0.0 {
        return b.heading;
    }
    let t = now.min(b.next_ms).saturating_sub(b.t_ms) as f32 / 1000.0;
    geo::wrap(b.heading + b.turn * t.min(b.turn_s))
}

/// `common::facing_at`.
pub fn facing_at(b: &Body, now: u64) -> f32 {
    let t = now.min(b.next_ms).saturating_sub(b.t_ms) as f32 / 1000.0;
    geo::facing(heading_at(b, now), b.face_off, b.face_turn, b.face_turn_s, t)
}

/// Where the body travels at `now`: its heading while it moves, None standing still.
pub fn travel_at(b: &Body, now: u64) -> Option<f32> {
    moving(b).then(|| heading_at(b, now))
}

fn due(now: u64, dur_s: f32, min_ms: u64) -> u64 {
    now + ((dur_s * 1000.0).round().max(0.0) as u64).max(min_ms)
}

fn set_motion(b: &mut Body, heading: f32, speed: f32, turn: f32, turn_s: f32) {
    b.heading = heading;
    b.turn = if turn_s > 0.0 { turn } else { 0.0 };
    b.turn_s = if turn != 0.0 { turn_s } else { 0.0 };
    b.vx = speed * heading.cos();
    b.vy = speed * heading.sin();
}

fn halt(b: &mut Body) {
    b.vx = 0.0;
    b.vy = 0.0;
    b.turn = 0.0;
    b.turn_s = 0.0;
}

fn put_face(b: &mut Body, f: geo::FaceSeg) {
    b.face_off = f.off;
    b.face_turn = if f.turn_s > 0.0 { f.turn } else { 0.0 };
    b.face_turn_s = if b.face_turn != 0.0 { f.turn_s } else { 0.0 };
}

fn resume_at(b: &Body, now: u64) -> u64 {
    if moving(b) && b.next_ms < now {
        return b.next_ms.max(now.saturating_sub(RESUME_MS)).max(b.t_ms);
    }
    now
}

fn anchor(b: &mut Body, now: u64) {
    let dt = now.min(b.next_ms).saturating_sub(b.t_ms) as f32 / 1000.0;
    let v = speed_of(b);
    let (x, y, h) = geo::pose(b.x, b.y, b.heading, v, b.turn, b.turn_s, dt);
    b.x = x;
    b.y = y;
    b.t_ms = now;
    let left = (b.turn_s - dt).max(0.0);
    set_motion(b, geo::wrap(h), v, if left > 0.0 { b.turn } else { 0.0 }, left);
    let off = geo::face_off(b.face_off, b.face_turn, b.face_turn_s, dt);
    let face_left = (b.face_turn_s - dt).max(0.0);
    b.face_off = off;
    b.face_turn = if face_left > 0.0 { b.face_turn } else { 0.0 };
    b.face_turn_s = if b.face_turn != 0.0 { face_left } else { 0.0 };
}

fn turn_to(b: &mut Body, want: f32, rate: f32, slack: f32) -> bool {
    let off = geo::face_off(b.face_off, b.face_turn, b.face_turn_s, 0.0);
    let Some(((legs, legs_s), face)) = geo::stand_facing(b.heading, off, want, rate, slack) else { return false };
    if legs_s > 0.0 {
        let h = b.heading;
        set_motion(b, h, 0.0, legs, legs_s);
    }
    put_face(b, face);
    true
}

impl Drive {
    pub fn new(laws: Laws, heading: f32) -> Self {
        let map = Map::from_chunks(2048, 2048, std::iter::empty());
        let b = Body { x: 1024.0, y: 1024.0, heading, next_ms: IDLE, speed: laws.walk, ..Default::default() };
        Self { b, st: Steer::default(), laws, map, rows: Vec::new() }
    }

    fn put(&mut self, now: u64) {
        self.rows.push((now, self.b));
    }

    fn settle_face(&mut self, before: f32, had_off: bool) {
        let (b, st, l) = (&mut self.b, &self.st, &self.laws);
        let rate = l.tune.turn_rate.max(0.5);
        if !st.look_on && !had_off {
            b.face_off = 0.0;
            b.face_turn = 0.0;
            b.face_turn_s = 0.0;
            return;
        }
        let mv = moving(b);
        if !mv && st.look_on && !st.walking {
            b.face_off = geo::wrap(before - b.heading);
            b.face_turn = 0.0;
            b.face_turn_s = 0.0;
            turn_to(b, st.look, rate, l.slack);
            return;
        }
        let f = geo::walk_facing(before, b.heading, b.turn, b.turn_s, st.look_on.then_some(st.look), l.limit, rate);
        put_face(b, f);
        if let Some(s) = f.due_s {
            b.next_ms = b.next_ms.min(due(b.t_ms, s, MIN_STEP_MS));
        }
    }

    /// One steering update (`motion::update` for a walk under the keys or none).
    fn update(&mut self, now: u64) {
        let before = facing_at(&self.b, resume_at(&self.b, now));
        let had_off = self.b.face_off != 0.0 || self.b.face_turn != 0.0;
        let v_cur = speed_of(&self.b);
        let t0 = resume_at(&self.b, now);
        anchor(&mut self.b, t0);
        if self.st.walking {
            let want = geo::Want { dir: self.st.gy.atan2(self.st.gx), speed: self.b.speed.max(0.1), agile: false, max_dt: self.laws.steer_s };
            let seg = geo::plan(&self.map, (self.b.x, self.b.y), self.b.heading, v_cur, want, &self.laws.tune);
            set_motion(&mut self.b, geo::wrap(seg.heading), seg.speed, seg.turn, seg.turn_s);
            self.b.next_ms = if seg.speed == 0.0 && seg.turn == 0.0 { due(t0, seg.dur.max(0.25), MIN_STEP_MS) } else { due(t0, seg.dur, MIN_STEP_MS) };
        } else {
            halt(&mut self.b);
            self.b.next_ms = IDLE;
        }
        self.settle_face(before, had_off);
    }

    fn start(&mut self, now: u64, dir: (f32, f32), speed: f32) {
        let n = dir.0.hypot(dir.1);
        self.st.walking = true;
        self.st.gx = dir.0 / n;
        self.st.gy = dir.1 / n;
        self.b.speed = speed;
        self.update(now);
        self.put(now);
    }

    fn brake(&mut self, now: u64) {
        self.st.walking = false;
        if self.b.next_ms == IDLE && !moving(&self.b) {
            return;
        }
        let t0 = resume_at(&self.b, now);
        anchor(&mut self.b, t0);
        let cut = self.b.turn_s > 0.0;
        let v = speed_of(&self.b) * 0.6;
        if v < 0.3 {
            halt(&mut self.b);
            self.b.next_ms = IDLE;
        } else {
            let h = self.b.heading;
            set_motion(&mut self.b, h, v, 0.0, 0.0);
            self.b.next_ms = due(t0, 0.3, MIN_STEP_MS);
        }
        // `motion::turn_cut`.
        if cut && self.b.face_turn != 0.0 {
            let rate = self.laws.tune.turn_rate.max(0.5);
            let facing = geo::wrap(self.b.heading + self.b.face_off);
            let f = geo::walk_facing(facing, self.b.heading, 0.0, 0.0, self.st.look_on.then_some(self.st.look), self.laws.limit, rate);
            put_face(&mut self.b, f);
        }
        self.put(now);
    }

    fn face(&mut self, now: u64, want: f32) {
        if self.b.next_ms != IDLE || moving(&self.b) {
            return;
        }
        anchor(&mut self.b, now);
        let rate = self.laws.tune.turn_rate.max(0.5);
        if turn_to(&mut self.b, want, rate, 0.05) {
            self.b.next_ms = IDLE;
            self.put(now);
        }
    }

    /// `motion::intent` and `motion::look` at `now`.
    pub fn input(&mut self, now: u64, i: Input) {
        match i {
            Input::Move { dir, run } => {
                let unit = dir.and_then(|(x, y)| {
                    let n = x.hypot(y);
                    (n > 1e-3).then(|| (x / n, y / n))
                });
                let same = match unit {
                    None => !self.st.walking,
                    Some(u) => self.st.walking && self.st.run == run && u.0 * self.st.gx + u.1 * self.st.gy > 0.9998,
                };
                if same {
                    return;
                }
                let keep = self.st.walking && self.st.run == run;
                self.st.run = run;
                match unit {
                    None => self.brake(now),
                    Some(u) => {
                        let speed = if keep { self.b.speed } else { self.laws.walk * if run { self.laws.run } else { 1.0 } };
                        self.start(now, u, speed)
                    }
                }
            }
            Input::Look { dir } => {
                let want = dir.and_then(|(x, y)| (x.hypot(y) > 1e-3).then(|| y.atan2(x)));
                let mv = moving(&self.b);
                let slack = self.laws.slack;
                match want {
                    None if !self.st.look_on => return,
                    Some(w) if self.st.look_on && geo::wrap(w - self.st.look).abs() <= slack && (mv || geo::wrap(w - facing_at(&self.b, now)).abs() <= slack) => return,
                    Some(w) if !self.st.look_on && !mv && geo::wrap(w - facing_at(&self.b, now)).abs() <= slack => return,
                    _ => {}
                }
                self.st.look_on = want.is_some();
                if let Some(w) = want {
                    self.st.look = w;
                }
                if self.st.walking && mv {
                    let (gx, gy, speed) = (self.st.gx, self.st.gy, self.b.speed);
                    self.start(now, (gx, gy), speed);
                } else if let (Some(w), false) = (want, mv) {
                    self.face(now, w);
                }
            }
        }
    }

    /// Run the steering updates that fall due up to `until` (each at the first tick after it).
    pub fn run_to(&mut self, until: u64) {
        while self.b.next_ms != IDLE {
            let tick = ((self.b.next_ms as f64 / TICK_MS).ceil() * TICK_MS).ceil() as u64;
            if tick > until {
                break;
            }
            self.update(tick);
            self.put(tick);
        }
    }
}

/// Replay `inputs` (authority ms, in order) and sample the facing and the travel every
/// `step_ms` from `from` to `to`: (t, facing, travel or None standing).
pub fn replay(laws: Laws, heading: f32, inputs: &[(u64, Input)], from: u64, to: u64, step_ms: u64) -> (Vec<(u64, f32, Option<f32>)>, Drive) {
    let t0 = inputs.first().map_or(from, |i| i.0).min(from);
    let mut d = Drive::new(laws, heading);
    d.b.t_ms = t0;
    let mut out = Vec::new();
    let mut k = 0;
    let mut t = from;
    loop {
        // Inputs before the sample, with the updates due before each.
        while k < inputs.len() && inputs[k].0 <= t {
            d.run_to(inputs[k].0);
            d.input(inputs[k].0, inputs[k].1);
            k += 1;
        }
        d.run_to(t);
        if t >= from {
            out.push((t, facing_at(&d.b, t), travel_at(&d.b, t)));
        }
        if t >= to {
            break;
        }
        t += step_ms;
    }
    (out, d)
}

/// Facing's largest change (radians, along its path) within any `win_ms` of a sampled track,
/// and the number of separate stretches in which it changed more than `over` within `win_ms`.
pub fn jumps(track: &[(u64, f32, Option<f32>)], win_ms: u64, over: f32) -> (f32, usize) {
    // Unwrap the facing so a turn through ±π is not a jump.
    let mut u = Vec::with_capacity(track.len());
    let mut acc = 0.0f32;
    for (i, s) in track.iter().enumerate() {
        if i > 0 {
            acc += geo::wrap(s.1 - track[i - 1].1);
        } else {
            acc = s.1;
        }
        u.push((s.0, acc));
    }
    let (mut worst, mut count, mut in_jump) = (0.0f32, 0usize, false);
    for i in 0..u.len() {
        let (mut lo, mut hi) = (u[i].1, u[i].1);
        let mut j = i;
        while j < u.len() && u[j].0 <= u[i].0 + win_ms {
            lo = lo.min(u[j].1);
            hi = hi.max(u[j].1);
            j += 1;
        }
        let span = hi - lo;
        worst = worst.max(span);
        if span > over && !in_jump {
            count += 1;
        }
        in_jump = span > over;
    }
    (worst, count)
}
