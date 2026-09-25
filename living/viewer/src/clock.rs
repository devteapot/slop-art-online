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

/// Server URL and database: `LIVING_SERVER`/`LIVING_DB` natively, `?server=…&db=…` on the web.
pub fn endpoint() -> (String, String) {
    #[cfg(target_arch = "wasm32")]
    {
        let params = web_sys::window()
            .and_then(|w| w.location().search().ok())
            .and_then(|s| web_sys::UrlSearchParams::new_with_str(&s).ok());
        let get = |k: &str| params.as_ref().and_then(|p| p.get(k)).filter(|v| !v.is_empty());
        (
            get("server").unwrap_or_else(|| DEFAULT_SERVER.into()),
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
