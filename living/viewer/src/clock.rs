//! Wall clock and endpoint configuration for native and browser builds.

pub const DEFAULT_SERVER: &str = "http://127.0.0.1:3300";
pub const DEFAULT_DB: &str = "living";

/// Unix time in milliseconds (the authority's time base).
pub fn now_ms() -> u64 {
    #[cfg(target_arch = "wasm32")]
    {
        js_sys::Date::now() as u64
    }
    #[cfg(not(target_arch = "wasm32"))]
    {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_millis() as u64)
            .unwrap_or(0)
    }
}

/// Optional season preview (`?season=winter` on the web, `LIVING_SEASON` natively).
pub fn season_override() -> Option<usize> {
    #[cfg(target_arch = "wasm32")]
    let v = web_sys::window()
        .and_then(|w| w.location().search().ok())
        .and_then(|s| web_sys::UrlSearchParams::new_with_str(&s).ok())
        .and_then(|p| p.get("season"));
    #[cfg(not(target_arch = "wasm32"))]
    let v = std::env::var("LIVING_SEASON").ok();
    v.and_then(|s| living_rules::SEASONS.iter().position(|n| *n == s.to_ascii_lowercase()))
}

/// Server URL and database: `LIVING_SERVER`/`LIVING_DB` natively, `?server=…&db=…` on the web.
/// A page served from a public host (the tunnel) defaults to its own origin, which forwards
/// the subscription path to SpacetimeDB.
pub fn endpoint() -> (String, String) {
    #[cfg(target_arch = "wasm32")]
    {
        let location = web_sys::window().map(|w| w.location());
        let params = location
            .as_ref()
            .and_then(|l| l.search().ok())
            .and_then(|s| web_sys::UrlSearchParams::new_with_str(&s).ok());
        let get = |k: &str| params.as_ref().and_then(|p| p.get(k)).filter(|v| !v.is_empty());
        let origin = location
            .filter(|l| l.hostname().is_ok_and(|h| !matches!(h.as_str(), "127.0.0.1" | "localhost" | "[::1]")))
            .and_then(|l| l.origin().ok());
        (
            get("server").or(origin).unwrap_or_else(|| DEFAULT_SERVER.into()),
            get("db").unwrap_or_else(|| DEFAULT_DB.into()),
        )
    }
    #[cfg(not(target_arch = "wasm32"))]
    {
        (
            std::env::var("LIVING_SERVER").unwrap_or_else(|_| DEFAULT_SERVER.into()),
            std::env::var("LIVING_DB").unwrap_or_else(|_| DEFAULT_DB.into()),
        )
    }
}
