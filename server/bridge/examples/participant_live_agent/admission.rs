//! Optional run-owned, cross-process tools/call admission. Slots are never created here.
#[cfg(unix)]
use std::os::unix::fs::MetadataExt;
use std::{
    fs::{File, OpenOptions, TryLockError},
    path::{Component, PathBuf},
    sync::Arc,
    time::Duration,
};
use tokio::{sync::watch, time::Instant};

pub struct Admission {
    directory: PathBuf,
    identities: Vec<(u64, u64)>,
}
pub struct Permit {
    // Each permit owns a fresh open-file description. Closing it releases the lock.
    _file: File,
    pub slot: usize,
}
impl Admission {
    pub fn from_env() -> Result<Option<Arc<Self>>, String> {
        Self::from_parts(
            std::env::var_os("SAO_EXTERNAL_RPC_ADMISSION_DIR").map(PathBuf::from),
            std::env::var_os("SAO_EXTERNAL_RPC_CONCURRENCY")
                .map(|v| v.into_string().map_err(|_| "invalid admission concurrency"))
                .transpose()?,
        )
        .map(|value| value.map(Arc::new))
    }
    pub fn from_parts(
        directory: Option<PathBuf>,
        count: Option<String>,
    ) -> Result<Option<Self>, String> {
        let (directory, count) = match (directory, count) {
            (None, None) => return Ok(None),
            (Some(directory), Some(count)) => (directory, count),
            _ => return Err("admission directory and concurrency must both be set".into()),
        };
        let count = count
            .parse::<usize>()
            .ok()
            .filter(|n| (1..=36).contains(n))
            .ok_or("admission concurrency must be 1..36")?;
        if !directory.is_absolute()
            || directory
                .components()
                .any(|c| matches!(c, Component::ParentDir))
            || directory
                .canonicalize()
                .map_err(|_| "admission directory unavailable")?
                != directory
            || !std::fs::symlink_metadata(&directory)
                .map_err(|_| "admission directory unavailable")?
                .is_dir()
        {
            return Err("admission directory must be absolute and contain no symlinks".into());
        }
        let mut admission = Self {
            directory,
            identities: Vec::with_capacity(count),
        };
        for slot in 0..count {
            let (_, identity) = admission.open_slot(slot)?;
            if admission.identities.contains(&identity) {
                return Err("admission slots must be distinct files".into());
            }
            admission.identities.push(identity);
        }
        Ok(Some(admission))
    }
    pub fn count(&self) -> usize {
        self.identities.len()
    }
    fn open_slot(&self, slot: usize) -> Result<(File, (u64, u64)), String> {
        let path = self.directory.join(format!("slot-{slot:02}.lock"));
        let before = std::fs::symlink_metadata(&path).map_err(|_| "admission slot unavailable")?;
        if !before.is_file() || before.file_type().is_symlink() {
            return Err("admission slot must be a regular file".into());
        }
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(path)
            .map_err(|_| "admission slot unavailable")?;
        let after = file
            .metadata()
            .map_err(|_| "admission slot metadata unavailable")?;
        #[cfg(unix)]
        {
            let identity = (after.dev(), after.ino());
            if !after.is_file()
                || before.nlink() != 1
                || after.nlink() != 1
                || (before.dev(), before.ino()) != identity
                || self
                    .identities
                    .get(slot)
                    .is_some_and(|expected| *expected != identity)
            {
                return Err("admission slot changed or has multiple links".into());
            }
            Ok((file, identity))
        }
        #[cfg(not(unix))]
        {
            let _ = (file, after);
            Err("RPC admission requires Unix file identity validation".into())
        }
    }
    pub async fn acquire(
        &self,
        deadline: Instant,
        cancel: &mut watch::Receiver<Option<String>>,
    ) -> Result<Permit, &'static str> {
        let mut offset = std::process::id() as usize % self.count();
        loop {
            if cancel.borrow().is_some() {
                return Err("MCP admission cancelled; request not sent");
            }
            if Instant::now() >= deadline {
                return Err("MCP admission deadline; request not sent");
            }
            for index in 0..self.count() {
                let slot = (offset + index) % self.count();
                let (file, _) = self
                    .open_slot(slot)
                    .map_err(|_| "MCP admission failed; request not sent")?;
                match file.try_lock() {
                    Ok(()) => {
                        let permit = Permit { _file: file, slot };
                        if cancel.borrow().is_some() {
                            return Err("MCP admission cancelled; request not sent");
                        }
                        if Instant::now() >= deadline {
                            return Err("MCP admission deadline; request not sent");
                        }
                        return Ok(permit);
                    }
                    Err(TryLockError::WouldBlock) => (),
                    Err(TryLockError::Error(_)) => {
                        return Err("MCP admission failed; request not sent")
                    }
                }
            }
            offset = (offset + 1) % self.count();
            tokio::select! {
                biased;
                _ = cancel.changed() => return Err("MCP admission cancelled; request not sent"),
                _ = tokio::time::sleep_until(deadline) => return Err("MCP admission deadline; request not sent"),
                _ = tokio::time::sleep(Duration::from_millis(10)) => (),
            }
        }
    }
}

#[cfg(test)]
pub mod tests {
    use super::*;
    pub fn fixture(count: usize) -> (PathBuf, Arc<Admission>) {
        let root = std::env::temp_dir().join(format!("sao-admission-{}", rand::random::<u64>()));
        std::fs::create_dir(&root).unwrap();
        for slot in 0..count {
            File::create(root.join(format!("slot-{slot:02}.lock"))).unwrap();
        }
        let value = Admission::from_parts(Some(root.clone()), Some(count.to_string()))
            .unwrap()
            .unwrap();
        (root, Arc::new(value))
    }
    #[test]
    fn validates_pair_count_and_slot_identity() {
        assert!(Admission::from_parts(None, None).unwrap().is_none());
        assert!(Admission::from_parts(None, Some("1".into())).is_err());
        let (root, _) = fixture(1);
        assert!(Admission::from_parts(Some(root.clone()), None).is_err());
        for count in ["0", "37", "x", ""] {
            assert!(Admission::from_parts(Some(root.clone()), Some(count.into())).is_err());
        }
        assert!(Admission::from_parts(Some(root.clone()), Some("2".into())).is_err());
        #[cfg(unix)]
        {
            let slot = root.join("slot-00.lock");
            std::fs::hard_link(&slot, root.join("slot-01.lock")).unwrap();
            assert!(Admission::from_parts(Some(root.clone()), Some("2".into())).is_err());
            std::fs::remove_file(root.join("slot-01.lock")).unwrap();
            std::os::unix::fs::symlink(&slot, root.join("slot-01.lock")).unwrap();
            assert!(Admission::from_parts(Some(root.clone()), Some("2".into())).is_err());
            let alias = root.with_extension("alias");
            std::os::unix::fs::symlink(&root, &alias).unwrap();
            assert!(Admission::from_parts(Some(alias.clone()), Some("1".into())).is_err());
            std::fs::remove_file(alias).unwrap();
        }
        std::fs::remove_dir_all(root).unwrap();
    }
    #[tokio::test]
    async fn fresh_handles_contend_and_drop_releases() {
        let (root, admission) = fixture(1);
        let (_sender, mut cancel) = watch::channel(None);
        let first = admission
            .acquire(Instant::now() + Duration::from_secs(1), &mut cancel)
            .await
            .unwrap();
        assert!(admission
            .acquire(Instant::now() + Duration::from_millis(25), &mut cancel)
            .await
            .err()
            .unwrap()
            .contains("deadline"));
        drop(first);
        let second = admission
            .acquire(Instant::now() + Duration::from_secs(1), &mut cancel)
            .await
            .unwrap();
        drop(second);
        std::fs::remove_dir_all(root).unwrap();
    }
}
