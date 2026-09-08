//! Explicit owner snapshot transport selection and strict procedure wire parsing.
//! SpacetimeDB 2.7.1 HTTP/CLI returns an untyped SATS sum: [0, value] or
//! [1, error]. An HTTP success or successful CLI exit can still contain Err.
use serde::{
    de::{self, IgnoredAny, SeqAccess, Visitor},
    Deserialize, Deserializer, Serialize,
};
use std::{fmt, marker::PhantomData};

pub const INVENTORY_PROCEDURE: &str = "sim_owned_run_ids";
pub const EXPORT_PROCEDURE: &str = "sim_export_owned_run";
pub const API_ENV: &str = "SAO_OWNER_SNAPSHOT_API";

#[derive(Clone, Copy, Debug, Default, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum SnapshotApi {
    #[default]
    Sql,
    Procedure,
}

impl SnapshotApi {
    pub fn from_setting(value: Option<&str>) -> Result<Self, String> {
        match value {
            None | Some("sql") => Ok(Self::Sql),
            Some("procedure") => Ok(Self::Procedure),
            Some(_) => Err("SAO_OWNER_SNAPSHOT_API must be sql or procedure".into()),
        }
    }

    pub fn from_env() -> Result<Self, String> {
        Self::from_env_or(Self::Sql)
    }

    /// Live hosts may choose one-shot exports without changing historical runner defaults.
    pub fn from_env_or(default: Self) -> Result<Self, String> {
        match std::env::var(API_ENV) {
            Ok(value) => Self::from_setting(Some(&value)),
            Err(std::env::VarError::NotPresent) => Ok(default),
            Err(_) => Err("SAO_OWNER_SNAPSHOT_API must be sql or procedure".into()),
        }
    }
}

struct ProcedureReply<T>(Result<T, String>);

impl<'de, T: Deserialize<'de>> Deserialize<'de> for ProcedureReply<T> {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct ReplyVisitor<T>(PhantomData<T>);
        impl<'de, T: Deserialize<'de>> Visitor<'de> for ReplyVisitor<T> {
            type Value = ProcedureReply<T>;

            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("a two-element owner procedure result")
            }

            fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Self::Value, A::Error> {
                let tag: u8 = seq
                    .next_element()?
                    .ok_or_else(|| de::Error::custom("missing result tag"))?;
                let result = match tag {
                    0 => Ok(seq
                        .next_element()?
                        .ok_or_else(|| de::Error::custom("missing result payload"))?),
                    1 => {
                        let error: String = seq
                            .next_element()?
                            .ok_or_else(|| de::Error::custom("missing result error"))?;
                        Err(if error == "run unavailable" {
                            error
                        } else {
                            "owner procedure failed".into()
                        })
                    }
                    _ => return Err(de::Error::custom("unknown result tag")),
                };
                if seq.next_element::<IgnoredAny>()?.is_some() {
                    return Err(de::Error::custom("unexpected result element"));
                }
                Ok(ProcedureReply(result))
            }
        }
        deserializer.deserialize_tuple(2, ReplyVisitor(PhantomData))
    }
}

fn reply<'de, T: Deserialize<'de>>(text: &'de str) -> Result<T, String> {
    let result: ProcedureReply<T> =
        serde_json::from_str(text).map_err(|_| "invalid owner procedure response")?;
    result.0
}

/// Preserve the exact inner JSON string, including whitespace and number spelling.
/// The consumer still validates and decodes the World and its expected run/cursor.
pub fn parse_export_json(text: &str) -> Result<String, String> {
    reply(text)
}

pub fn parse_inventory(text: &str) -> Result<Vec<String>, String> {
    let ids: Vec<String> = reply(text)?;
    if ids.iter().any(String::is_empty) || ids.windows(2).any(|pair| pair[0] >= pair[1]) {
        return Err("invalid owner inventory ordering".into());
    }
    Ok(ids)
}

pub const AUDIT_PROCEDURE: &str = "sim_export_owned_audit";
pub fn parse_audit_page(text: &str, run: &str, start: u64, end: u64) -> Result<Vec<String>, String> {
    if start == 0 || end < start { return Err("invalid audit range".into()); }
    let bodies: Vec<String> = reply(text)?;
    if bodies.len() as u64 != (end - start).min(4096) { return Err("audit page incomplete".into()); }
    #[derive(Deserialize)]
    struct Header { run: String, id: u64 }
    for (n, body) in bodies.iter().enumerate() {
        let h: Header = serde_json::from_str(body).map_err(|_| "invalid audit event")?;
        if h.run != run || h.id != start + n as u64 { return Err("audit event gap or scope mismatch".into()); }
    }
    Ok(bodies)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn audit_pages_preserve_original_json_and_reject_wrong_scope_or_gaps() {
        let body = "{ \"run\":\"r\", \"id\":1, \"n\":1.00 }";
        let wire = serde_json::to_string(&(0u8, vec![body])).unwrap();
        assert_eq!(parse_audit_page(&wire, "r", 1, 2).unwrap(), vec![body]);
        assert!(parse_audit_page(&wire, "other", 1, 2).is_err());
        assert!(parse_audit_page(&wire, "r", 2, 3).is_err());
        assert!(parse_audit_page("[0,[]]", "r", 1, 2).is_err());
        assert!(parse_audit_page("[1,\"run unavailable\"]", "r", 1, 2).is_err());
    }
    #[test]
    fn explicit_transport_defaults_to_historical_sql_and_rejects_unknown_modes() {
        assert_eq!(SnapshotApi::from_setting(None).unwrap(), SnapshotApi::Sql);
        assert_eq!(
            SnapshotApi::from_setting(Some("sql")).unwrap(),
            SnapshotApi::Sql
        );
        assert_eq!(
            SnapshotApi::from_setting(Some("procedure")).unwrap(),
            SnapshotApi::Procedure
        );
        for value in ["", "auto", "SQL", "procedure,sql"] {
            assert!(SnapshotApi::from_setting(Some(value)).is_err());
        }
        assert_eq!(
            serde_json::to_string(&SnapshotApi::Procedure).unwrap(),
            "\"procedure\""
        );
    }

    #[test]
    fn procedure_success_preserves_exact_world_bytes_and_inventory() {
        let body = "{ \"run\":\"r\",\"next_event\":2,\"text\":\"quote\\\" slash\\\\ newline\\n λ\",\"n\":1.0 }";
        let wire = serde_json::to_string(&(0u8, body)).unwrap() + "\n";
        assert_eq!(parse_export_json(&wire).unwrap(), body);
        assert_eq!(parse_inventory("[0,[]]").unwrap(), Vec::<String>::new());
        assert_eq!(
            parse_inventory("[0,[\"a\",\"b\"]]").unwrap(),
            vec!["a", "b"]
        );
    }

    #[test]
    fn procedure_error_cannot_be_mistaken_for_transport_success_or_leak_details() {
        assert_eq!(
            parse_export_json("[1,\"run unavailable\"]").unwrap_err(),
            "run unavailable"
        );
        assert_eq!(
            parse_inventory("[1,\"private source content\"]").unwrap_err(),
            "owner procedure failed"
        );
    }

    #[test]
    fn malformed_named_sql_and_wrong_typed_responses_fail_without_fallback() {
        for wire in [
            "",
            "null",
            "[0]",
            "[0,\"x\",1]",
            "[2,\"x\"]",
            "[true,\"x\"]",
            "[0.0,\"x\"]",
            "[-1,\"x\"]",
            "[256,\"x\"]",
            "[1,null]",
            "{\"ok\":\"x\"}",
            "[{\"rows\":[[\"x\"]]}]",
            "[0,{}]",
            "[0,\"x\"] trailing",
            "notice\n[0,\"x\"]",
        ] {
            assert!(parse_export_json(wire).is_err(), "accepted {wire}");
        }
        for wire in [
            "[0,[1]]",
            "[0,[\"\"]]",
            "[0,[\"a\",\"a\"]]",
            "[0,[\"b\",\"a\"]]",
            "[0,\"a\"]",
        ] {
            assert!(parse_inventory(wire).is_err(), "accepted {wire}");
        }
    }
}
