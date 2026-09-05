//! Target compatibility evidence for ADR 016; not a production runtime.
pub fn evaluate() -> mlua::Result<i64> {
    let lua = mlua::Lua::new();
    lua.sandbox(true)?;
    lua.load("local function step(x) return x + 1 end; return step(0)")
        .eval()
}

#[test]
fn native_embedding() {
    assert_eq!(evaluate().unwrap(), 1);
}
