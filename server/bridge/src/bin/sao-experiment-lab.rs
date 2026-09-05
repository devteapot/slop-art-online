//! Local experiment directory and same-origin access to independently versioned Bevy hosts.
//! No simulation stepping, participant credentials or model decisions live in this process.
use axum::{body::{to_bytes,Body},extract::{Request,State},http::{header,StatusCode},response::{Html,IntoResponse,Response},routing::get,Json,Router};
use serde_json::{json,Value};
use std::{collections::hash_map::DefaultHasher,hash::{Hash,Hasher},path::{Path,PathBuf},sync::Arc};

struct Lab { root:PathBuf, viewer:PathBuf, client:reqwest::Client }
#[derive(Clone)]
struct Session { id:String, port:u16, db:String, view:Value }
type Shared=Arc<Lab>;
fn read(path:&Path)->Value {std::fs::read(path).ok().and_then(|b|serde_json::from_slice(&b).ok()).unwrap_or(Value::Null)}
fn scan(root:&Path,depth:usize,found:&mut Vec<PathBuf>) {
    if depth==0{return;}
    if root.join("pilot.json").is_file(){found.push(root.to_owned());return;}
    if let Ok(entries)=std::fs::read_dir(root) {
        for entry in entries.flatten() {
            if entry.file_type().is_ok_and(|t|t.is_dir()) {
                let name=entry.file_name();let name=name.to_string_lossy();
                if !name.starts_with('.') && !matches!(name.as_ref(),"implementations"|"bundles"|"target"|"node_modules"|"client"|"server"|"simulation") {
                    scan(&entry.path(),depth-1,found);
                }
            }
        }
    }
}
fn file_count(root:&Path)->usize {
    std::fs::read_dir(root).ok().into_iter().flatten().flatten().map(|e| {
        if e.file_type().is_ok_and(|t|t.is_dir()){file_count(&e.path())}
        else {usize::from((e.file_name().to_string_lossy().starts_with("harness-") || e.file_name()=="external.json") && e.path().extension().is_some_and(|e|e=="json"))}
    }).sum()
}
fn sessions(lab:&Lab)->Vec<Session> {
    let mut dirs=vec![];scan(&lab.root,5,&mut dirs);
    let mut result=vec![];
    for dir in dirs {
        let pilot=read(&dir.join("pilot.json"));let active=read(&dir.join("active.json"));
        let Some(run)=active["run"].as_str() else {continue;};
        let Some(db)=active["db"].as_str() else {continue;};
        let Some(url)=active["url"].as_str().and_then(|s|reqwest::Url::parse(s).ok()) else {continue;};
        if url.scheme()!="http" || !matches!(url.host_str(),Some("127.0.0.1"|"localhost")){continue;}
        let Some(port)=url.port() else {continue;};
        let mut h=DefaultHasher::new();dir.hash(&mut h);let id=format!("s{:016x}",h.finish());
        let scenario=read(&dir.join(run).join("scenario.json"));let metrics=read(&dir.join("metrics.json"));
        let aggregate=read(&dir.join("LIVE_RESULT.json"));
        let parent=dir.parent().unwrap_or(&dir);let batch=read(&parent.join("batch.json"));
        let label=dir.file_name().unwrap_or_default().to_string_lossy().to_string();
        let batch_label=if batch.is_object(){parent.file_name().unwrap_or_default().to_string_lossy().to_string()}else{"Previous experiments".into()};
        let implementation=pilot["implementation_manifest"]["label"].as_str().unwrap_or("recorded working tree");
        let actors=metrics["players"].as_array().or_else(||scenario["players"].as_array());
        let alive=actors.map_or(0,|p|p.iter().filter(|p|p["health"].as_i64().unwrap_or(0)>0).count());
        let phase=pilot["phase"].as_str().unwrap_or("unknown");
        let time=aggregate["seconds"].as_f64().unwrap_or(metrics["time_ms"].as_f64().unwrap_or(0.)/1000.);
        let calls=aggregate["total_calls"].as_u64().map(|n|n as usize).unwrap_or_else(||
            file_count(&dir.join(run).join("reasoning"))+file_count(&dir.join(run).join("live-inference")));
        let view=json!({"id":id,"label":label,"batch":batch_label,"hypothesis":batch["hypothesis"],"implementation":implementation,
            "run":run,"phase":phase,"seconds":time,"duration_seconds":pilot["minutes"].as_u64().unwrap_or(5)*60,
            "population":scenario["players"].as_array().map_or(0,Vec::len),"alive":alive,"calls":calls,
            "arenas":scenario["arenas"],"url":format!("/session/{id}/#{id}"),"started_at":pilot["started_at"],
            "engine_errors":aggregate["engine_errors"].as_array().map(Vec::len),"scope_violations":aggregate["scope_violations"].as_array().map(Vec::len)});
        result.push(Session{id,port,db:db.into(),view});
    }
    result.sort_by(|a,b|b.view["started_at"].as_f64().unwrap_or(0.).total_cmp(&a.view["started_at"].as_f64().unwrap_or(0.)));
    result
}
async fn index()->Html<&'static str>{Html(include_str!("../../experiment_lab.html"))}
async fn catalog(State(lab):State<Shared>)->Json<Value>{Json(json!({"sessions":sessions(&lab).into_iter().map(|s|s.view).collect::<Vec<_>>()}))}
fn failure(status:StatusCode,message:&str)->Response{(status,message.to_string()).into_response()}
async fn proxy(State(lab):State<Shared>,mut request:Request)->Response {
    let path=request.uri().path().to_owned();let entries=sessions(&lab);
    let (session,path)=if let Some(rest)=path.strip_prefix("/session/") {
        let Some((id,tail))=rest.split_once('/') else {return failure(StatusCode::NOT_FOUND,"Session path missing");};
        let Some(session)=entries.iter().find(|s|s.id==id) else {return failure(StatusCode::NOT_FOUND,"Unknown experiment session");};
        (session,format!("/{tail}"))
    } else if let Some(rest)=path.strip_prefix("/v1/database/") {
        let Some((db,tail))=rest.split_once('/') else {return failure(StatusCode::NOT_FOUND,"Database path missing");};
        if tail!="subscribe" {return failure(StatusCode::NOT_FOUND,"Only the session subscription transport is exposed");}
        let Some(session)=entries.iter().find(|s|s.db==db) else {return failure(StatusCode::NOT_FOUND,"Unknown experiment database");};
        (session,path)
    } else {return failure(StatusCode::NOT_FOUND,"Unknown lab route");};
    // Use the common observer client for comparisons; each direct host retains its frozen viewer.
    if request.method()==axum::http::Method::GET && path!="/v1/database/" && !path.starts_with("/api/") && !path.starts_with("/v1/") {
        if path.split('/').any(|p|p==".."||p.starts_with('.')) {return failure(StatusCode::NOT_FOUND,"Invalid asset path");}
        let file=lab.viewer.join(if path=="/" {"index.html"}else{path.trim_start_matches('/')});
        return match tokio::fs::read(&file).await {
            Ok(body)=> {
                let mime=match file.extension().and_then(|e|e.to_str()).unwrap_or("") {"html"=>"text/html","js"=>"text/javascript","wasm"=>"application/wasm","css"=>"text/css",_=>"application/octet-stream"};
                ([(header::CONTENT_TYPE,mime)],body).into_response()
            },
            Err(_)=>failure(StatusCode::NOT_FOUND,"Observer client asset unavailable")
        };
    }
    let url=format!("http://127.0.0.1:{}{}{}",session.port,path,request.uri().query().map(|q|format!("?{q}")).unwrap_or_default());
    let websocket=request.headers().get(header::UPGRADE).is_some_and(|v|v=="websocket");
    let mut upstream=lab.client.request(request.method().clone(),url);
    for (name,value) in request.headers() {
        if !matches!(name.as_str(),"host"|"content-length") {upstream=upstream.header(name,value);}
    }
    let incoming=if websocket {Some(hyper::upgrade::on(&mut request))}else{None};
    if !websocket {
        let body=match to_bytes(request.into_body(),1024*1024).await {Ok(b)=>b,Err(_)=>return failure(StatusCode::PAYLOAD_TOO_LARGE,"Request too large")};
        upstream=upstream.body(body);
    }
    let upstream=match upstream.send().await {Ok(r)=>r,Err(_)=>return failure(StatusCode::BAD_GATEWAY,"This session host is offline. Its recorded results remain available in the experiment directory.")};
    let status=upstream.status();let mut response=Response::builder().status(status);
    for (name,value) in upstream.headers() {
        if !matches!(name.as_str(),"transfer-encoding"|"content-length") {response=response.header(name,value);}
    }
    if websocket && status==StatusCode::SWITCHING_PROTOCOLS {
        tokio::spawn(async move {
            if let (Ok(client),Ok(mut server))=tokio::join!(incoming.unwrap(),upstream.upgrade()) {
                let mut client=hyper_util::rt::TokioIo::new(client);
                let _=tokio::io::copy_bidirectional(&mut client,&mut server).await;
            }
        });
        return response.body(Body::empty()).unwrap();
    }
    match upstream.bytes().await {Ok(body)=>response.body(Body::from(body)).unwrap(),Err(_)=>failure(StatusCode::BAD_GATEWAY,"Session response unavailable")}
}
#[tokio::main]
async fn main()->Result<(),Box<dyn std::error::Error+Send+Sync>> {
    let root=std::env::var("SAO_LAB_OUTPUT").map(PathBuf::from).unwrap_or_else(|_|PathBuf::from("output"));
    let port=std::env::var("SAO_LAB_PORT").unwrap_or("18930".into());
    let lab=Arc::new(Lab{root,viewer:PathBuf::from("client/dist-participant"),client:reqwest::Client::builder().redirect(reqwest::redirect::Policy::none()).connect_timeout(std::time::Duration::from_secs(3)).build()?});
    let router=Router::new().route("/",get(index)).route("/api/lab",get(catalog)).fallback(proxy).with_state(lab);
    let listener=tokio::net::TcpListener::bind(format!("127.0.0.1:{port}")).await?;
    println!("Experiment lab: http://127.0.0.1:{port}");axum::serve(listener,router).await?;Ok(())
}
