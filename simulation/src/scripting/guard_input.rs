//! Exact dependency projection for the bundled guard source. Interpretation and
//! provenance ordering remain in Rhai; custom sources keep the full contract.
use super::*;
use crate::Condition;

thread_local! {
    // A future bundled law edit must not silently inherit this dependency contract.
    static CONTRACT_MATCHES: bool = format!("{:x}", Sha256::digest(include_bytes!("../../scripts/law.rhai")))
        == "593033f72233dca88d901e271485cd6df5212275519f2d2056111dad85ca4fce";
}

#[derive(Default)]
struct Reads {
    danger: BTreeSet<i32>,
    sites: BTreeMap<i32, (bool, bool)>,
    records: BTreeSet<String>,
    care: BTreeSet<u32>,
}
impl Reads {
    fn collect(&mut self, condition: &Condition, position: i32) {
        match condition {
            Condition::All { conditions } | Condition::Any { conditions } => {
                for condition in conditions {
                    self.collect(condition, position);
                }
            }
            Condition::Not { condition } => self.collect(condition, position),
            Condition::Danger { location } => {
                self.danger.insert(location.unwrap_or(position));
            }
            Condition::FoodAt { location, .. } => self.sites.entry(*location).or_default().0 = true,
            Condition::ShelterAt { location, .. } => {
                self.sites.entry(*location).or_default().1 = true
            }
            Condition::HasKnowledge { record } => {
                self.records.insert(record.clone());
            }
            Condition::NeedsCare { target } => {
                self.care.insert(*target);
            }
            Condition::At { .. } | Condition::Resource { .. } => (),
        }
    }
}
impl Registry {
    pub(crate) fn guard_subjective(&self, player: &Player, condition: &Condition) -> Value {
        let bundled = CONTRACT_MATCHES.with(|matches| *matches)
            && self
                .resolve("law")
                .ok()
                .and_then(|r| self.definition(&r).ok())
                .is_some_and(|law| {
                    law.dependencies.is_empty()
                        && law.source == include_str!("../../scripts/law.rhai")
                });
        if !bundled {
            return subjective(player);
        }
        let mut reads = Reads::default();
        reads.collect(condition, player.position);
        let mut value = facts(player);
        value["charge"] = json!(0); // the authority supplies physical charge later
        value["memories"] = json!([]); // bundled guard never reads this collection
        value["beliefs"] = json!(reads.danger.iter().filter_map(|location| {
            // The bundled source chooses the first matching belief, not the last.
            player.beliefs.iter().find(|b| b.claim.location == *location)
                .map(|b| json!({"claim":{"location":b.claim.location,"danger":b.claim.danger},"source":b.source}))
        }).collect::<Vec<_>>());
        value["site_observations"] = json!(reads.sites.iter().filter_map(|(location, (food, shelter))| {
            // Site guards use the last matching observation in original order.
            player.site_observations.iter().rev().find(|m| m.kind == "site" && m.location == *location)
                .map(|m| {
                    let mut content = serde_json::Map::new();
                    if *food { content.insert("food".into(), m.content["food"].clone()); }
                    if *shelter { content.insert("shelter".into(), m.content["shelter"].clone()); }
                    json!({"kind":"site","location":m.location,"source":m.source,"content":content})
                })
        }).collect::<Vec<_>>());
        value["knowledge"] = json!(reads
            .records
            .iter()
            .filter_map(|record| {
                player
                    .knowledge
                    .iter()
                    .find(|h| h.record.id == *record)
                    .map(|h| json!({"record":{"id":h.record.id},"source":h.source}))
            })
            .collect::<Vec<_>>());
        let mut care: BTreeMap<u64, Value> = BTreeMap::new();
        if !reads.care.is_empty() {
            for memory in &player.site_observations {
                for person in memory.content["lifecycle"]["people"]
                    .as_array()
                    .into_iter()
                    .flatten()
                {
                    let Some(id) = person["id"]
                        .as_u64()
                        .filter(|id| u32::try_from(*id).is_ok_and(|id| reads.care.contains(&id)))
                    else {
                        continue;
                    };
                    if care
                        .get(&id)
                        .is_none_or(|old| old["source"].as_u64().unwrap_or(0) < memory.source)
                    {
                        care.insert(
                            id,
                            json!({"id":id,"location":memory.location,"source":memory.source,
                            "dependent":person["dependent"],"needs_care":person["needs_care"]}),
                        );
                    }
                }
            }
        }
        value["care_observations"] = json!(care.into_values().collect::<Vec<_>>());
        value
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{Belief, Known, Percept};
    fn player() -> Player {
        let scenario: crate::Scenario =
            serde_json::from_str(include_str!("../../../scenarios/survival.json")).unwrap();
        scenario.players[0].clone()
    }
    fn site(location: i32, source: u64, food: i32) -> Percept {
        Percept {
            source,
            tick: 0,
            kind: "site".into(),
            from: None,
            location,
            content: json!({"food":food,"shelter":2,"buildable":true,"food_source":null,
                "lifecycle":{"people":[{"id":2,"dependent":true,"needs_care":food>0}]}}),
        }
    }
    fn evaluate(
        laws: &Registry,
        p: Value,
        condition: &Condition,
    ) -> Result<(bool, Vec<u64>), String> {
        laws.law("guard", json!({"player":p,"condition":condition}))
    }
    #[test]
    fn projected_guards_match_all_condition_types_and_exact_source_order() {
        let laws = Registry::default();
        let mut p = player();
        p.position = 1;
        *p.site_observations = vec![site(1, 10, 9), site(2, 11, 0), site(1, 12, 2)];
        *p.memories = vec![site(1, 1, 99)];
        *p.beliefs = vec![
            Known {
                claim: Belief {
                    location: 1,
                    danger: true,
                    text: "first".into(),
                },
                source: 90,
                confidence: 70,
            },
            Known {
                claim: Belief {
                    location: 1,
                    danger: false,
                    text: "later".into(),
                },
                source: 91,
                confidence: 99,
            },
        ];
        *p.knowledge=vec![serde_json::from_value(json!({"record":{"id":"record","topic":"test","text":"report","author":1,"origin":80,"confidence":50},
            "source":81,"interpretation":null,"confidence":null})).unwrap()];
        let leaves:Vec<Condition>=serde_json::from_value(json!([
            {"kind":"at","location":1},{"kind":"at","location":2},
            {"kind":"has_knowledge","record":"record"},{"kind":"has_knowledge","record":"missing"},
            {"kind":"needs_care","target":2},{"kind":"needs_care","target":99},
            {"kind":"danger","location":null},{"kind":"danger","location":1},{"kind":"danger","location":2},
            {"kind":"food_at","location":1,"minimum":3},{"kind":"food_at","location":1,"minimum":1},
            {"kind":"shelter_at","location":1,"minimum":2},{"kind":"food_at","location":3,"minimum":1},
            {"kind":"resource","resource":"energy","comparison":"at_least","value":5},
            {"kind":"resource","resource":"hunger","comparison":"below","value":50}
        ])).unwrap();
        let mut conditions = leaves.clone();
        for chunk in leaves.chunks(4) {
            conditions.push(Condition::All {
                conditions: chunk.to_vec(),
            });
            conditions.push(Condition::Any {
                conditions: chunk.to_vec(),
            });
            conditions.push(Condition::Not {
                condition: Box::new(Condition::All {
                    conditions: chunk.to_vec(),
                }),
            });
        }
        for condition in conditions {
            assert_eq!(
                evaluate(&laws, subjective(&p), &condition).unwrap(),
                evaluate(&laws, laws.guard_subjective(&p, &condition), &condition).unwrap(),
                "{condition:?}"
            );
        }
        let combined = Condition::All {
            conditions: vec![leaves[6].clone(), leaves[9].clone(), leaves[6].clone()],
        };
        assert_eq!(
            evaluate(&laws, laws.guard_subjective(&p, &combined), &combined).unwrap(),
            (false, vec![90, 12, 90])
        );
    }
    #[test]
    fn resource_guards_do_not_hydrate_unrelated_private_history() {
        assert!(CONTRACT_MATCHES.with(|matches| *matches));
        let mut p = player();
        p.memories = crate::deferred::Deferred::load_with(|| panic!("unrelated memories read"));
        p.site_observations =
            crate::deferred::Deferred::load_with(|| panic!("unrelated site history read"));
        p.beliefs = crate::deferred::Deferred::load_with(|| panic!("unrelated beliefs read"));
        p.knowledge = crate::deferred::Deferred::load_with(|| panic!("unrelated knowledge read"));
        let laws = Registry::default();
        let condition = Condition::At {
            location: p.position,
        };
        assert_eq!(
            evaluate(&laws, laws.guard_subjective(&p, &condition), &condition).unwrap(),
            (true, vec![])
        );
        assert!(
            !p.memories.is_loaded()
                && !p.site_observations.is_loaded()
                && !p.beliefs.is_loaded()
                && !p.knowledge.is_loaded()
        );
    }
    #[test]
    fn exploration_does_not_expand_guards_but_custom_laws_keep_full_input() {
        let mut laws = Registry::default();
        let mut p = player();
        p.site_observations = (0..49)
            .map(|location| site(location, 100 + location as u64, 2))
            .collect();
        p.memories = p.site_observations[..16].to_vec().into();
        let condition = Condition::All {
            conditions: (0..7)
                .map(|group| Condition::All {
                    conditions: (0..7)
                        .map(|n| Condition::FoodAt {
                            location: group * 7 + n,
                            minimum: 1,
                        })
                        .collect(),
                })
                .collect(),
        };
        assert!(evaluate(&laws, subjective(&p), &condition)
            .unwrap_err()
            .contains("object map"));
        assert_eq!(
            evaluate(&laws, laws.guard_subjective(&p, &condition), &condition).unwrap(),
            (true, (100..149).collect())
        );
        laws.history
            .get_mut("law")
            .unwrap()
            .get_mut(&1)
            .unwrap()
            .source
            .push_str("\n// custom source: preserve complete hook input\n");
        assert_eq!(laws.guard_subjective(&p, &condition), subjective(&p));
    }
}
