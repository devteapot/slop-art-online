//! Same-origin transport for forwarded browsers. The database still authenticates every client.
use super::*;
use axum::extract::Request;

pub async fn subscribe(
    State(app): State<Shared>,
    Path(database): Path<String>,
    mut request: Request,
) -> ApiResult {
    if database != app.db {
        return Err((StatusCode::NOT_FOUND, "unknown database".into()));
    }
    if request.headers().contains_key(header::ORIGIN)
        && !browser_origin_allowed(&app.origin, &app.local_origin, request.headers())
    {
        return Err((StatusCode::FORBIDDEN, "browser origin rejected".into()));
    }
    if !request
        .headers()
        .get(header::UPGRADE)
        .is_some_and(|v| v == "websocket")
    {
        return Err((StatusCode::BAD_REQUEST, "WebSocket upgrade required".into()));
    }
    // Fixed local authority and database; this is not an arbitrary forwarding endpoint.
    let mut upstream = reqwest::Client::new().get(format!(
        "{}/v1/database/{}/subscribe?{}",
        app.server,
        app.db,
        request.uri().query().unwrap_or("")
    ));
    for name in [
        "connection",
        "upgrade",
        "sec-websocket-key",
        "sec-websocket-version",
        "sec-websocket-protocol",
        "authorization",
    ] {
        if let Some(value) = request.headers().get(name) {
            upstream = upstream.header(name, value);
        }
    }
    let upstream = upstream.send().await.map_err(|_| {
        (
            StatusCode::BAD_GATEWAY,
            "authority connection unavailable".into(),
        )
    })?;
    if upstream.status() != StatusCode::SWITCHING_PROTOCOLS {
        return Err((
            StatusCode::BAD_GATEWAY,
            "authority refused WebSocket connection".into(),
        ));
    }
    let mut response = Response::builder().status(StatusCode::SWITCHING_PROTOCOLS);
    for name in [
        "connection",
        "upgrade",
        "sec-websocket-accept",
        "sec-websocket-protocol",
    ] {
        if let Some(value) = upstream.headers().get(name) {
            response = response.header(name, value);
        }
    }
    let incoming = hyper::upgrade::on(&mut request);
    tokio::spawn(async move {
        if let (Ok(client), Ok(mut database)) = tokio::join!(incoming, upstream.upgrade()) {
            let mut client = hyper_util::rt::TokioIo::new(client);
            let _ = tokio::io::copy_bidirectional(&mut client, &mut database).await;
        }
    });
    Ok(response.body(Body::empty()).map_err(error)?)
}
