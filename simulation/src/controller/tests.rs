use super::*;
use runtime::{Dispatch, Runtime};
use participant::{Command, Request, API_VERSION};
fn world() -> World {
    let s = serde_json::from_str(include_str!("../../../scenarios/survival.json")).unwrap();
    let mut w = World::new("client-boundary-test".into(),s).unwrap();
    w.enable_client_controllers().unwrap();
    w
}
fn request(w: &World, actor:u32, id:&str, command:Command) -> Request {
    Request {api_version:API_VERSION.into(),request_id:id.into(),control_epoch:w.participants[&actor].control_epoch,command}
}
#[test]
fn composed_initialization_matches_persisted_phases_and_safe_evidence() {
    for body in [include_str!("../../../scenarios/survival.json"),
        include_str!("../../../scenarios/faction-world-reality.json"),
        include_str!("../../../scenarios/population-reproduction.json"),
        include_str!("../../../scenarios/research-invention.json")] {
        let seed:Scenario=serde_json::from_str(body).unwrap();
        let initial=World::new("initialization-parity".into(),seed.clone()).unwrap();
        let audit=serde_json::to_value(&initial.events).unwrap();
        // The former authority path saved each phase and loaded a World with
        // no pending audit events before importing permitted initial records.
        let mut persisted:World=serde_json::from_value(serde_json::to_value(&initial).unwrap()).unwrap();
        persisted.enable_participants();
        for event in &initial.events {persisted.record_initial_participant_event(event);}
        let composed=World::new_participant("initialization-parity".into(),seed.clone()).unwrap();
        assert_eq!(serde_json::to_value(&composed).unwrap(),serde_json::to_value(&persisted).unwrap(),"participant {}",seed.name);
        assert_eq!(serde_json::to_value(&composed.events).unwrap(),audit);
        persisted=serde_json::from_value(serde_json::to_value(&persisted).unwrap()).unwrap();
        persisted.enable_client_controllers().unwrap();
        let client=World::new_client("initialization-parity".into(),seed.clone()).unwrap();
        assert_eq!(serde_json::to_value(&client).unwrap(),serde_json::to_value(&persisted).unwrap(),"client {}",seed.name);
        assert_eq!(serde_json::to_value(&client.events).unwrap(),audit,"one unchanged ordered audit");
        for state in client.participants.values() {
            assert!(state.experiences.iter().all(|e|e.kind!="initialization"),"operator seed truth is not personal evidence");
        }
    }
}
#[test]
fn remembered_targets_share_unchanged_sets_and_detach_new_identities() {
    let w=world();let actor=w.players[0].id;
    let mut original=w.participants[&actor].client_controller.clone().unwrap();
    original.known_targets=(1..=200).collect();
    let mut candidate=original.clone();
    candidate.action=Some(success("changed-action"));
    for id in 1..=200 {assert!(!candidate.remember_target(id));}
    assert!(candidate.known_targets.same_snapshot(&original.known_targets),"duplicate observations never copy the target set");
    assert!(candidate.remember_target(u32::MAX));
    assert!(!candidate.known_targets.same_snapshot(&original.known_targets));
    assert!(!original.known_targets.contains(&u32::MAX));
    assert!(candidate.known_targets.contains(&u32::MAX));
    let mut legacy=serde_json::to_value(&original).unwrap();
    legacy["known_targets"]=json!([3,1,3,u32::MAX]);
    let decoded:Authority=serde_json::from_value(legacy).unwrap();
    assert_eq!(serde_json::to_value(&decoded.known_targets).unwrap(),json!([1,3,u32::MAX]),"same legacy set/JSON semantics");
    let retained=candidate.clone();
    candidate.known_targets.clear();
    assert_eq!(retained.known_targets.len(),201,"general mutable access still detaches");
    assert_eq!(original.known_targets.len(),200);
}
#[test]
fn real_death_witnesses_preserve_shared_remembered_target_snapshots() {
    let mut w=world();let position=w.players[0].position;
    for player in &mut w.players {player.position=position;}
    let ids:Vec<_>=w.players.iter().map(|p|p.id).collect();
    for state in w.participants.values_mut() {
        state.client_controller.as_mut().unwrap().known_targets=ids.iter().copied().collect();
    }
    let before=w.clone();let cause=w.players[0].last_cause.unwrap_or(1);
    let start=w.events.len();
    w.damage(0,10000,None,cause,"attack").unwrap();
    assert!(w.players[0].health<=0);assert!(before.players[0].health>0);
    let witnesses:Vec<_>=w.events[start..].iter().filter(|e|e.kind=="perception" && e.data["kind"]=="death").collect();
    assert_eq!(witnesses.len(),ids.len()-1,"exercise the real dense witness path");
    for actor in ids {
        let old=before.participants[&actor].client_controller.as_ref().unwrap();
        let current=w.participants[&actor].client_controller.as_ref().unwrap();
        assert!(current.known_targets.same_snapshot(&old.known_targets),"retained identities unchanged for actor {actor}");
        assert_eq!(serde_json::to_value(&current.known_targets).unwrap(),serde_json::to_value(&old.known_targets).unwrap());
    }
}
#[test]
fn finite_action_and_human_intent_share_physical_execution_and_paid_costs() {
    let mut agent=world();let mut human=agent.clone();let actor=agent.players[0].id;
    human.players[0].controller=Controller::Human;
    let action=Action::new(Skill::Rest);
    let req=request(&agent,actor,"agent-rest",Command::StartAction {
        expected_revision:agent.players[0].generation,action:action.clone()});
    assert!(agent.participant_apply(actor,req).unwrap().ok);
    assert!(human.participant_client_intent(actor,Decision {reason:"human rest".into(),policy:None,
        actions:vec![action],reflections:vec![]}).unwrap().unwrap().ok);
    for _ in 0..60 {agent.advance_ms(50);human.advance_ms(50);}
    let body=|w:&World| {let p=&w.players[0];json!({"health":p.health,"hunger":p.hunger,"energy":p.energy,
        "food":p.food,"position":p.position,"fear":p.fear,"failures":p.failures})};
    assert_eq!(body(&agent),body(&human));
    assert_eq!(agent.timing.action_ready_ms,human.timing.action_ready_ms);
}
#[test]
fn death_interrupts_finite_action_and_rejects_new_controller_effects() {
    let mut w=world();let actor=w.players[0].id;
    let req=request(&w,actor,"rest",Command::StartAction {expected_revision:w.players[0].generation,action:Action::new(Skill::Rest)});
    assert!(w.participant_apply(actor,req).unwrap().ok);w.advance_ms(50);
    let cause=w.event(None,"test_disturbance",vec![],json!({"purpose":"permanent death boundary"}));
    w.damage(0,10000,None,cause,"environment").unwrap();
    assert!(w.players[0].health<=0);
    assert_eq!(w.participants[&actor].client_controller.as_ref().unwrap().action.as_ref().unwrap().status,Status::Interrupted);
    let req=request(&w,actor,"after-death",Command::StartAction {expected_revision:w.players[0].generation,action:Action::new(Skill::Rest)});
    assert!(!w.participant_apply(actor,req).unwrap().ok);
    for _ in 0..60 {w.advance_ms(50);}
    assert!(w.players[0].health<=0);
}
#[test]
fn authority_executes_finite_action_without_policy_or_subjective_updates() {
    let mut w = world();
    let actor = w.players[0].id;
    let req = request(&w,actor,"wait-one",Command::StartAction {expected_revision:w.players[0].generation,action:Action::new(Skill::Wait)});
    assert!(w.participant_apply(actor,req.clone()).unwrap().ok);
    let accepted = w.next_event;
    assert!(w.participant_apply(actor,req).unwrap().ok);
    assert_eq!(accepted,w.next_event,"duplicate command has no repeated effect");
    for _ in 0..60 {w.advance_ms(50);}
    assert_eq!(w.participants[&actor].client_controller.as_ref().unwrap().action.as_ref().unwrap().status,Status::Success);
    assert!(w.players[0].memories.is_empty());
    assert!(w.players[0].beliefs.is_empty());
    assert!(w.participants[&actor].activity.is_empty());
    assert!(!w.events.iter().filter(|e|e.id >= accepted).any(|e|matches!(e.kind.as_str(),"policy_tick"|"guard_evaluated"|"identity_change")));
    let req = request(&w,actor,"stale",Command::StartAction {expected_revision:0,action:Action::new(Skill::Wait)});
    assert!(!w.participant_apply(actor,req).unwrap().ok);


}
fn success(id:&str) -> ActionState { ActionState {request_id:id.into(),revision:1,accepted_event:1,status:Status::Success,attempt:Some(2)} }
#[test]
fn client_once_and_sequence_survive_checkpoint_and_wait_for_authority() {
    let w=world(); let a=w.players[0].id;
    let mut r=Runtime::new(&w.participants[&a].client_controller.as_ref().unwrap().bootstrap).unwrap();
    let action=|| Node::Action {action:Action::new(Skill::Wait)};
    r.replace(r.policy_revision,Node::Once {child:Box::new(Node::Sequence {children:vec![action(),action()]})},"test").unwrap();
    let laws=scripting::Registry::default();
    assert!(matches!(r.tick("one",None,&laws,0).unwrap(),Some(Dispatch::Start(_))));
    assert!(r.tick("unused",None,&laws,0).unwrap().is_none());
    r=serde_json::from_str(&serde_json::to_string(&r).unwrap()).unwrap();
    assert!(r.tick("unused",Some(&success("one")),&laws,0).unwrap().is_none());
    assert!(matches!(r.tick("two",Some(&success("one")),&laws,0).unwrap(),Some(Dispatch::Start(_))));
    assert!(r.tick("unused",Some(&success("two")),&laws,0).unwrap().is_none());
    assert!(r.state.once_completed.contains("root"));
    assert!(r.tick("three",Some(&success("two")),&laws,0).unwrap().is_none());
}
#[test]
fn false_guard_cancels_authority_action_without_simulating_a_result() {
    let w=world();let a=w.players[0].id;
    let mut r=Runtime::new(&w.participants[&a].client_controller.as_ref().unwrap().bootstrap).unwrap();
    let location=r.player.position;
    r.replace(r.policy_revision,Node::Guard {condition:policy::Condition::At {location},child:Box::new(Node::Action {action:Action::new(Skill::Wait)})},"test").unwrap();
    let laws=scripting::Registry::default();
    assert!(matches!(r.tick("one",None,&laws,0).unwrap(),Some(Dispatch::Start(_))));
    r.player.position+=1;
    let mut f=success("one");f.status=Status::Running;
    assert!(matches!(r.tick("cancel",Some(&f),&laws,0).unwrap(),Some(Dispatch::Cancel)));
    assert!(r.active.is_none());
}

#[test]
fn patch_to_failed_guard_cancels_previous_action_after_checkpoint() {
    let w=world(); let a=w.players[0].id;
    let mut r=Runtime::new(&w.participants[&a].client_controller.as_ref().unwrap().bootstrap).unwrap();
    let laws=scripting::Registry::default();
    r.replace(r.policy_revision,Node::Action {action:Action::new(Skill::Wait)},"start").unwrap();
    assert!(matches!(r.tick("one",None,&laws,0).unwrap(),Some(Dispatch::Start(_))));
    r.patch(r.policy_revision,"root",Node::Guard {condition:policy::Condition::At {location:r.player.position+1},
        child:Box::new(Node::Action {action:Action::new(Skill::Wait)})},"stop").unwrap();
    r=serde_json::from_str(&serde_json::to_string(&r).unwrap()).unwrap();
    let mut feedback=success("one");feedback.status=Status::Running;
    assert!(matches!(r.tick("cancel",Some(&feedback),&laws,0).unwrap(),Some(Dispatch::Cancel)));
    assert!(r.state.active_path.is_none());
}

#[test]
fn private_reflection_requires_explicit_publication_for_physical_knowledge() {
    let mut w=world(); let actor=w.players[0].id;
    let mut runtime=Runtime::new(&w.participants[&actor].client_controller.as_ref().unwrap().bootstrap).unwrap();
    let record=knowledge::Record {id:"personal-report".into(),topic:"Food".into(),text:"A reported observation".into(),
        location:Some(w.players[0].position),author:actor,origin:1,confidence:40,
        program:None,experiment:None,law_program:None,law_experiment:None};
    w.receive_record(0,1,None,&record,"test report").unwrap();
    let experiences=w.participants[&actor].experiences.clone();
    let laws=scripting::Registry::default();
    for e in experiences.iter() {runtime.ingest(e.clone(),&laws).unwrap();}
    runtime.player.knowledge=w.players[0].knowledge.clone();
    let source=experiences.iter().find(|e|e.kind=="perception" && e.data["kind"]=="knowledge_report").unwrap().source;
    let reflection=Reflection {source,interpretation:"This is a tentative personal assessment.".into(),
        knowledge:Some(knowledge::KnowledgeDraft {topic:"Food".into(),text:"A tentative inference".into(),location:None,confidence:30}),
        caution_delta:1,trust_delta:0,belief:None};
    runtime.reflect(0,runtime.cursor,&[reflection.clone()],Some("private goal"),&[],&laws).unwrap();
    assert_eq!(runtime.knowledge_drafts.len(),1);
    assert_eq!(w.players[0].knowledge.len(),1);
    assert!(w.players[0].knowledge[0].interpreted_source.is_none());
    let command=Command::PublishKnowledge {observed_cursor:runtime.cursor,source,
        interpretation:reflection.interpretation,knowledge:reflection.knowledge};
    let req=request(&w,actor,"publish",command);
    let receipt=w.participant_apply(actor,req.clone()).unwrap();assert!(receipt.ok,"{:?}",receipt.error);
    assert_eq!(w.players[0].knowledge.len(),2);
    assert_eq!(w.players[0].knowledge[0].interpreted_source,Some(source));
    assert!(w.players[0].current_goal.is_none());assert!(w.players[0].beliefs.is_empty());
    assert!(w.players[0].knowledge.iter().all(|h|h.record.experiment.is_none() && h.record.program.is_none()));
    assert!(w.participant_apply(actor,req).unwrap().ok);assert_eq!(w.players[0].knowledge.len(),2);
    let req=request(&w,actor,"forged",Command::PublishKnowledge {observed_cursor:runtime.cursor,source:u64::MAX,
        interpretation:"Invented evidence must fail".into(),knowledge:None});
    assert!(!w.participant_apply(actor,req).unwrap().ok);
    let req=request(&w,actor,"lease",Command::ReadObservation {after:0,limit:256});
    assert!(w.participant_apply(actor,req).unwrap().ok);
    let expires=w.participants[&actor].evidence_leases.last().unwrap().expires_ms;
    assert!(w.participants[&actor].evidence_leases.last().unwrap().observed_cursor>runtime.cursor);
    w.participants.get_mut(&actor).unwrap().experiences.clear();
    let publish=||Command::PublishKnowledge {observed_cursor:runtime.cursor,source,
        interpretation:"Assessment of my still-leased report".into(),knowledge:None};
    let req=request(&w,actor,"leased-publication",publish());
    assert!(w.participant_apply(actor,req).unwrap().ok);
    w.timing.time_ms=expires+1;
    let req=request(&w,actor,"expired-publication",publish());
    assert!(!w.participant_apply(actor,req).unwrap().ok);
}
