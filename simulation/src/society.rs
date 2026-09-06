//! Authored public geography and initial institutions. Office and affiliation
//! confer no engine or law-editing capability. Physical access is held by assets.
use crate::*;
use std::collections::BTreeSet;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SocietySeed {
    pub version: u32,
    pub regions: Vec<Region>,
    pub organizations: Vec<Organization>,
    pub offices: Vec<Office>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Region {
    pub id: String,
    pub label: String,
    pub kind: RegionKind,
    pub bounds: spatial::Bounds,
    /// Explicit initial designation; operative editing is a separate capability.
    #[serde(default)]
    pub territorial_editors: Vec<u32>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum RegionKind { Homeland, City, Wild, Mixed }
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Organization {
    pub id: String,
    pub label: String,
    pub members: Vec<u32>,
    pub stations: Vec<u32>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Office {
    pub id: String,
    pub label: String,
    pub region: String,
    pub holder: u32,
    pub represented_group: Option<String>,
}
fn valid_id(id: &str) -> bool {
    !id.is_empty() && id.len() <= 80 && id.chars().all(|c| c.is_ascii_alphanumeric() || "-_.".contains(c))
}
pub fn validate(scenario: &Scenario) -> Result<(), String> {
    let Some(seed) = &scenario.society else { return Ok(()); };
    let map = scenario.map.as_ref().ok_or("society geography requires a surveyed grid")?;
    if seed.version != 1 || seed.regions.len() > 64 || seed.organizations.len() > 64 || seed.offices.len() > 128 {
        return Err("invalid society definition version or capacity".into());
    }
    let people: BTreeSet<_> = scenario.players.iter().map(|p|p.id).collect();
    let mut ids = BTreeSet::new();
    for region in &seed.regions {
        let b=&region.bounds;
        if !valid_id(&region.id) || !ids.insert(region.id.clone()) || region.label.is_empty() || region.label.len()>160
            || b.x<0 || b.y<0 || b.width<1 || b.height<1 || b.width>map.width || b.height>map.height
            || b.x>map.width-b.width || b.y>map.height-b.height
            || region.territorial_editors.len()>16 || region.territorial_editors.iter().any(|id|!people.contains(id))
            || region.territorial_editors.iter().collect::<BTreeSet<_>>().len()!=region.territorial_editors.len() {
            return Err("invalid society region or designated editor".into());
        }
    }
    let regions=ids.clone(); ids.clear();
    for org in &seed.organizations {
        if !valid_id(&org.id) || !ids.insert(org.id.clone()) || org.label.is_empty() || org.label.len()>160
            || org.members.is_empty() || org.members.len()>lifecycle::MAX_TOTAL_ACTORS
            || org.members.iter().any(|id|!people.contains(id))
            || org.members.iter().collect::<BTreeSet<_>>().len()!=org.members.len()
            || org.stations.len()>128 || org.stations.iter().collect::<BTreeSet<_>>().len()!=org.stations.len() {
            return Err("invalid society organization".into());
        }
        for station in &org.stations {
            if !scenario.infrastructure.as_ref().is_some_and(|s| s.stations.iter().any(|s|s.id==*station && org.members.contains(&s.owner))) {
                return Err("organization facilities require an explicit member owner".into());
            }
        }
    }
    let organizations=ids.clone(); ids.clear();
    for office in &seed.offices {
        if !valid_id(&office.id) || !ids.insert(office.id.clone()) || office.label.is_empty() || office.label.len()>160
            || !regions.contains(&office.region) || !people.contains(&office.holder)
            || office.represented_group.as_ref().is_some_and(|g|!organizations.contains(g)) {
            return Err("invalid civic office".into());
        }
    }
    Ok(())
}
impl World {
    pub(super) fn society_survey(&self, actor: Option<u32>) -> Value {
        let Some(seed) = &self.initial.society else {return json!([]);};
        let scope = actor.and_then(|id| self.map_for_actor(id)).and_then(|map| map.bounds);
        json!(seed.regions.iter().filter_map(|r| {
            let mut bounds = r.bounds.clone();
            if let Some(scope) = &scope {
                let right = (bounds.x + bounds.width).min(scope.x + scope.width);
                let bottom = (bounds.y + bounds.height).min(scope.y + scope.height);
                bounds.x = bounds.x.max(scope.x); bounds.y = bounds.y.max(scope.y);
                bounds.width = right - bounds.x; bounds.height = bottom - bounds.y;
                if bounds.width <= 0 || bounds.height <= 0 {return None;}
            }
            Some(json!({"id":r.id,"label":r.label,"kind":r.kind,"bounds":bounds}))
        }).collect::<Vec<_>>())
    }
    pub(super) fn society_context(&self, actor: u32) -> Value {
        let Some(seed) = &self.initial.society else {return Value::Null;};
        // Only surveyed boundaries and this person's authored affiliations are
        // supplied. An institution listing never reveals member locations/minds.
        json!({"version":seed.version,
            "survey":self.society_survey(Some(actor)),
            "initial_memberships":seed.organizations.iter().filter(|o|o.members.contains(&actor)).map(|o|json!({"id":o.id,"label":o.label})).collect::<Vec<_>>(),
            "initial_offices":seed.offices.iter().filter(|o|o.holder==actor).collect::<Vec<_>>(),
            "office_contract":"Civic office and cultural membership do not confer infrastructure access or reality editing. Initial affiliations describe starting institutions; choices and beliefs remain yours."})
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn scenario() -> Scenario {
        serde_json::from_str(include_str!("../../scenarios/settlement-renewable.json")).unwrap()
    }
    #[test]
    fn civic_office_discloses_own_affiliation_without_editor_or_remote_member_state() {
        let mut seed=scenario();
        seed.society=Some(SocietySeed {version:1,
            regions:vec![Region{id:"city".into(),label:"Public city".into(),kind:RegionKind::City,
                bounds:spatial::Bounds{x:1,y:1,width:10,height:8},territorial_editors:vec![]}],
            organizations:vec![Organization{id:"association".into(),label:"Resident association".into(),members:vec![1,2],stations:vec![]}],
            offices:vec![Office{id:"council-seat".into(),label:"Resident representative".into(),holder:1,
                region:"city".into(),represented_group:Some("association".into())}]});
        let world=World::new("society".into(),seed).unwrap();
        let own=world.society_context(1);
        assert_eq!(own["initial_offices"].as_array().unwrap().len(),1);
        assert_eq!(own["initial_memberships"][0]["id"],"association");
        assert!(own["initial_memberships"][0].get("members").is_none());
        assert!(own["survey"][0].get("territorial_editors").is_none());
        assert_eq!(world.society_context(2)["initial_offices"],json!([]));
        assert_eq!(world.society_context(3)["initial_memberships"],json!([]));
        assert!(world.initial.society.as_ref().unwrap().regions[0].territorial_editors.is_empty());
    }
    #[test]
    fn surveyed_regions_are_clipped_to_personal_arena_without_editor_leakage() {
        let mut seed=scenario();
        seed.society=Some(SocietySeed {version:1, regions:vec![
            Region{id:"crossing".into(),label:"Shared range".into(),kind:RegionKind::Wild,
                bounds:spatial::Bounds{x:1,y:1,width:10,height:8},territorial_editors:vec![1]},
            Region{id:"remote".into(),label:"Remote range".into(),kind:RegionKind::City,
                bounds:spatial::Bounds{x:12,y:1,width:2,height:2},territorial_editors:vec![]}
        ], organizations:vec![], offices:vec![]});
        let mut world=World::new("survey".into(),seed).unwrap();
        world.actor_arenas.clear();
        world.initial.arenas=vec![spatial::Arena{id:"own".into(),label:"Own".into(),environment:"test".into(),variant:"test".into(),
            bounds:spatial::Bounds{x:0,y:0,width:6,height:5},actors:vec![1],controllers:Default::default()}];
        let own=world.society_survey(Some(1));
        assert_eq!(own.as_array().unwrap().len(),1);
        assert_eq!(own[0]["bounds"],json!({"x":1,"y":1,"width":5,"height":4}));
        assert!(!own.to_string().contains("territorial_editors"));
        assert_eq!(world.society_survey(None).as_array().unwrap().len(),2);
        let projected=crate::client_view::snapshot(&world,false,1,&[]);
        assert_eq!(projected["regions"],own);
    }
    #[test]
    fn large_seed_uses_existing_actor_capacity_and_invalid_facilities_fail_initialization() {
        let mut seed=scenario();
        let template=seed.players[0].clone();
        seed.players=(1..=36).map(|id|{let mut p=template.clone();p.id=id;p}).collect();
        seed.starting_behaviors.clear();seed.knowledge.clear();seed.arenas.clear();seed.lifecycle=None;
        let world=World::new("thirty-six".into(),seed.clone()).unwrap();
        assert_eq!(world.players.len(),36);
        seed.society=Some(SocietySeed{version:1,regions:vec![],offices:vec![],organizations:vec![Organization {
            id:"members".into(),label:"Independent members".into(),members:vec![1,2],stations:vec![999]}]});
        assert!(World::new("invalid".into(),seed).unwrap_err().contains("explicit member owner"));
    }
}
