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

/// The database owner's token, which the observer needs: what it shows (minds, thoughts,
/// beliefs, every body) is developer audit truth, private to the owner (docs/PERCEPTION.md).
/// Natively `LIVING_TOKEN`, else `.local/living/token` in the checkout (`just living-token`, as
/// the mind service reads it); on the web the page's `#token=…` fragment, which the browser
/// never sends to a server. Without one the observer connects anonymously and its private
/// subscriptions are refused.
pub fn owner_token() -> Option<String> {
    #[cfg(target_arch = "wasm32")]
    let t = web_sys::window()
        .and_then(|w| w.location().hash().ok())
        .and_then(|h| h.strip_prefix('#').and_then(|h| h.split('&').find_map(|kv| kv.strip_prefix("token=").map(str::to_string))));
    #[cfg(not(target_arch = "wasm32"))]
    let t = std::env::var("LIVING_TOKEN").ok().or_else(|| {
        let mut p = std::env::current_dir().ok()?;
        loop {
            if p.join("living").join("Cargo.toml").exists() {
                return std::fs::read_to_string(p.join(".local/living/token")).ok();
            }
            if !p.pop() {
                return None;
            }
        }
    });
    t.map(|t| t.trim().to_string()).filter(|t| !t.is_empty())
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
