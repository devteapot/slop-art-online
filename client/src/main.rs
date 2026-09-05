#[cfg(feature = "foundation")]
mod foundation;
#[cfg(feature = "foundation")]
fn main() { foundation::run(); }

#[cfg(not(feature = "foundation"))]
include!("legacy_main.rs");
