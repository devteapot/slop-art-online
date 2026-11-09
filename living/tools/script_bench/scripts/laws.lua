-- Port of three laws from living/scripts/skills.rhai to Lua 5.4 (same map-shaped input `a`).
-- Shared by piccolo (pure-Rust Lua) and mlua (PUC Lua 5.4, native only).

local function count(m, key)
  local n = m[key]
  if n == nil then return 0 end
  return n
end

local function inv(a, item) return count(a.actor.inv, item) end

local function within(ago, ms) return ago ~= nil and ago < ms end

local function cold(a)
  return a.night and a.actor.kind == "person" and not a.actor.near_fire and not a.actor.near_shelter and inv(a, "cloak") == 0
end

local function wet(a) return a.raining and a.actor.kind == "person" and not a.actor.near_shelter end

function rates(a)
  local actor = a.actor
  local kind = actor.kind
  local hunger
  if kind == "deer" then hunger = 6.0 elseif kind == "wolf" then hunger = 1.5 else hunger = 5.0 end
  local energy = -3.0
  local hp = 0.0
  local act = actor.activity
  if act == "sleep" then
    if actor.near_shelter then energy = 26.0 else energy = 16.0 end
    hunger = hunger * 0.5
  elseif act == "rest" then
    energy = 6.0
  elseif act == "block" then
    energy = -12.0
  end
  if actor.hunger >= 100.0 then
    hp = hp - 6.0
  elseif actor.hunger < 70.0 and actor.energy > 15.0 then
    hp = hp + 3.0
  end
  if actor.energy <= 0.0 then hp = hp - 2.0 end
  if actor.stage == "elder" then
    if hp > 0.0 then hp = hp * 0.5 end
    energy = energy * 1.3
  end
  if actor.stage == "infant" then
    if kind == "person" then hunger = hunger * 0.6 else hunger = hunger * 0.3 end
  end
  if energy < 0.0 then energy = energy / actor.endurance end
  if hp > 0.0 then hp = hp * actor.vitality end
  if wet(a) then
    if inv(a, "cloak") > 0 then energy = energy - 1.0 else energy = energy - 2.5 end
  end
  if cold(a) then
    if a.season == "winter" then hp = hp - 5.0 else hp = hp - 2.0 end
  end
  return { hunger = hunger, energy = energy, hp = hp }
end

local cooldowns = { strike = 650, bowshot = 900, firebolt = 4000, heal = 8000, dodge = 900, block = 400 }
-- `switch` in the script; a table here is the idiomatic Lua form (built once at load).
function combat_cooldown(skill) return cooldowns[skill] or 0 end

local costs = { strike = 2.0, bowshot = 1.5, firebolt = 12.0, heal = 15.0, dodge = 4.0, block = 1.0 }
local function combat_cost(skill) return costs[skill] or 0.0 end
local function winded(a) if a.actor.energy < combat_cost(a.skill) then return "too tired" end return "" end

local function young(a) return a.actor.stage == "infant" or a.actor.stage == "child" end
local function yielding(a) return within(a.actor.yielded_ago, 20000.0) end

local function dares(a)
  local kind = a.actor.kind
  if kind == "person" or a.target.kind ~= "person" then return "" end
  if a.actor.bold then return "" end
  if a.actor.hurt_by == a.target.id and within(a.actor.hurt_ago, 10000.0) then return "" end
  local prey = 0
  if kind == "wolf" then prey = prey + count(a.actor.sensed, "deer") end
  if a.actor.hunger >= 85.0 and prey == 0 then return "" end
  local t = a.target
  if t.stage == "infant" or t.stage == "child" then return "" end
  if t.max_hp > 0.0 and t.hp < 0.35 * t.max_hp then return "" end
  if not t.near_fire and (t.activity == "sleep" or (a.night and t.company == 0)) then return "" end
  return "you do not dare: people are dangerous"
end

local function attack_check(a)
  if a.actor.kind == "person" and young(a) then return "too young to fight" end
  if a.target.class ~= "creature" or not a.target.alive then return "nothing to attack" end
  if a.target.id == a.actor.id then return "cannot attack yourself" end
  if yielding(a) then return "you have yielded: you do not strike back while it holds" end
  local wary = dares(a)
  if wary ~= "" then return wary end
  return ""
end

function strike_check(a)
  local why = attack_check(a)
  if why ~= "" then return why end
  return winded(a)
end

local function armor(a) if count(a.target.inv, "armor") < 1 then return 1.0 end return 0.65 end

function strike_done(a)
  local dmg
  if inv(a, "spear") > 0 then dmg = 15.0 else dmg = 10.0 end
  dmg = dmg * a.actor.strength * a.actor.factor * armor(a)
  return { { op = "damage", amount = dmg }, { op = "vitals", energy = -combat_cost("strike") } }
end
