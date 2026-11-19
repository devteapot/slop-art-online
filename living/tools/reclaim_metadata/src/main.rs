// Read only from a private copy of the v2.14.1 control directory.
use serde_json::{json, Value};
use std::{collections::BTreeMap, env, fs, io, path::Path};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

fn number(bytes: &[u8]) -> u64 {
    u64::from_le_bytes(bytes.try_into().unwrap())
}

fn hex(bytes: &[u8]) -> String {
    bytes
        .iter()
        .rev()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn control(path: &Path) -> Result<Value> {
    for name in ["conf", "db"] {
        if !path.join(name).is_file() || fs::metadata(path.join(name))?.len() == 0 {
            return Err(format!("control copy missing {name}").into());
        }
    }
    let db = sled::Config::default()
        .path(path)
        .mode(sled::Mode::HighThroughput)
        .open()?;
    for name in ["database", "database_by_identity", "replica", "reverse_dns"] {
        if !db
            .tree_names()
            .iter()
            .any(|tree| tree.as_ref() == name.as_bytes())
        {
            return Err(format!("missing control tree {name}").into());
        }
    }
    let names = db.open_tree("reverse_dns")?;
    let mut databases = BTreeMap::new();
    for row in db.open_tree("database")?.iter() {
        let (key, value) = row?;
        if value.len() != 105 || key.as_ref() != number(&value[..8]).to_be_bytes() {
            return Err("invalid database key or BSATN layout".into());
        }
        let aliases = match names.get(&value[8..40])? {
            Some(value) => serde_json::from_slice::<Vec<String>>(&value)?,
            None => Vec::new(),
        };
        databases.insert(
            number(&value[..8]),
            json!({
                "identity": hex(&value[8..40]), "names": aliases
            }),
        );
    }
    // The secondary index must agree with the primary tree.
    let mut indexed = BTreeMap::new();
    for row in db.open_tree("database_by_identity")?.iter() {
        let (key, value) = row?;
        if value.len() != 105 || !key.iter().eq(value[8..40].iter().rev()) {
            return Err("invalid database-by-identity key or BSATN layout".into());
        }
        indexed.insert(number(&value[..8]), hex(&value[8..40]));
    }
    if databases
        .iter()
        .map(|(id, row)| (*id, row["identity"].as_str().unwrap().to_owned()))
        .collect::<BTreeMap<_, _>>()
        != indexed
    {
        return Err("control database indexes disagree".into());
    }
    let mut replicas = BTreeMap::new();
    for row in db.open_tree("replica")?.iter() {
        let (key, value) = row?;
        if value.len() != 25 || value[24] > 1 || key.as_ref() != number(&value[..8]).to_be_bytes() {
            return Err("invalid replica key or BSATN layout".into());
        }
        replicas.insert(number(&value[..8]), number(&value[8..16]));
    }
    let aliases = names
        .iter()
        .map(|row| -> Result<_> {
            let (key, value) = row?;
            if key.len() != 32 {
                return Err("invalid reverse DNS key".into());
            }
            Ok((hex(&key), serde_json::from_slice::<Vec<String>>(&value)?))
        })
        .collect::<Result<BTreeMap<_, _>>>()?;
    Ok(json!({"databases": databases, "replicas": replicas, "aliases": aliases}))
}

fn snapshot(path: &Path) -> Result<Value> {
    let input = fs::read(path)?;
    let data = if input.starts_with(&[0x28, 0xb5, 0x2f, 0xfd]) {
        let out = std::process::Command::new("zstd")
            .arg("-dc")
            .arg(path)
            .output()?;
        if !out.status.success() {
            return Err("snapshot decompression failed".into());
        }
        out.stdout
    } else {
        input
    };
    if data.len() < 81
        || &data[32..41] != b"\x04\0\0\0txyz\0"
        || blake3::hash(&data[32..]).as_bytes() != &data[..32]
    {
        return Err("unrecognized or corrupt snapshot metadata".into());
    }
    Ok(json!({"identity": hex(&data[41..73]), "replica": number(&data[73..81])}))
}

fn main() -> Result<()> {
    let mut args = env::args_os().skip(1);
    let control_path = args.next().ok_or("expected control-db copy")?;
    let control = control(Path::new(&control_path))?;
    let mut snapshots = BTreeMap::new();
    for line in io::stdin().lines() {
        let line = line?;
        let path = Path::new(&line);
        snapshots.insert(line.clone(), snapshot(path).unwrap_or(Value::Null));
    }
    println!("{}", json!({"control": control, "snapshots": snapshots}));
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn verifies_snapshot_hash_and_embedded_replica() {
        let dir = env::temp_dir().join(format!("trial-reclaim-test-{}", std::process::id()));
        fs::create_dir(&dir).unwrap();
        let path = dir.join("fixture.snapshot_bsatn");
        let mut payload = b"\x04\0\0\0txyz\0".to_vec();
        let mut identity = [0_u8; 32];
        identity[31] = 0xc2;
        payload.extend(identity);
        payload.extend(123_u64.to_le_bytes());
        let mut file = blake3::hash(&payload).as_bytes().to_vec();
        file.extend(payload);
        fs::write(&path, &file).unwrap();
        let parsed = snapshot(&path).unwrap();
        assert_eq!(parsed["replica"], 123);
        assert_eq!(parsed["identity"].as_str().unwrap(), format!("c2{:062}", 0));
        file[73] ^= 1;
        fs::write(&path, &file).unwrap();
        assert!(snapshot(&path).is_err());
        fs::remove_dir_all(dir).unwrap();
    }
}
