// The host only supplies facts and evaluates the resulting state proposal.
// Movement policy, resource cost, and composition are defined in scripts.
fn step(position, reserve, target) {
    if position == target || reserve < move_cost() {
        return [position, reserve];
    }
    let distance = if target > position { target - position } else { position - target };
    let amount = if distance < step_size() { distance } else { step_size() };
    let next = if target > position { position + amount } else { position - amount };
    [next, reserve - move_cost()]
}
step(x, energy, destination)
