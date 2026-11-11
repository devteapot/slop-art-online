// Cullet's goods, fires and recipes (docs/SMALL_CITY.md, "The land that feeds it"): data over
// the shipped rules, composed as a floor composes its laws (living_rules::floors::compose:
// each function here replaces the base one of its name, which stays as base_NAME). Nothing
// here is a rule: the rules that read these traits are the shipped script's (docs/WORLD_RULES.md,
// "Goods, recipes and fuel").
//
// The chain: kelp is gathered on the Wrack Strand and burnt to ash at any fire; ash and sand are
// melted into glass at the Cone, a furnace that burns peat; fish are smoked over peat at a
// smokehouse; roots are baked at an oven; lamp oil is rendered from fish at a fire and burnt in
// lamps. Numbers are first guesses, to be tuned in the soak (docs/SMALL_CITY.md, phase 4).

fn items() {
    base_items() + [
        // Gathered on the shore; burnt to ash (4 to 1).
        #{ name: "kelp" },
        // Ash is an alkali: glass takes any alkali.
        #{ name: "ash", alkali: true },
        #{ name: "sand" },
        #{ name: "glass" },
        // The staple, eaten raw or baked.
        #{ name: "roots", bakes_to: "baked_roots" },
        #{ name: "baked_roots" },
        #{ name: "greens" },
        // Cut on the Moss; what hearths, ovens, smokehouses and the Cone burn.
        #{ name: "peat", fuel: 1.0 },
        // Rendered from fish; what lamps burn.
        #{ name: "lamp_oil", oil: 1.0 },
    ]
}

fn nutrition(item) {
    switch item {
        "roots" => 14.0,
        "baked_roots" => 30.0,
        "greens" => 10.0,
        _ => base_nutrition(item),
    }
}

fn spoil_rate(item) {
    switch item {
        "roots" => 0.004,
        "baked_roots" => 0.01,
        "greens" => 0.03,
        _ => base_spoil_rate(item),
    }
}

// Fires that eat fuel. Rates are units a game hour while lit; warmth and light are metres.
fn structures() {
    base_structures() + [
        #{ name: "hearth", burns: #{ fuel: "fuel", rate: 0.5, warmth: 4.0, light: 8.0, holds: 12.0 } },
        #{ name: "oven", burns: #{ fuel: "fuel", rate: 1.0, warmth: 2.5, light: 3.0, holds: 8.0 } },
        // The Cone: the town's glass furnace, burning about as much as all the homes together.
        #{ name: "furnace", burns: #{ fuel: "fuel", rate: 3.0, warmth: 6.0, light: 10.0, holds: 40.0 } },
        #{ name: "smokehouse", roof: true, burns: #{ fuel: "fuel", rate: 0.5, warmth: 2.0, light: 2.0, holds: 8.0 } },
        #{ name: "lamp", burns: #{ fuel: "oil", rate: 0.25, light: 10.0, holds: 2.0 } },
    ]
}

// What the land gives. A fishing ground's spots share one stock when the seed says so (a
// resource node's `pool`).
fn resources() {
    base_resources() + [
        #{ name: "kelp_bed", yields: "kelp", regrow: 1.0, max: 6.0, ground: ["sand"], by_water: true, gather_ms: 2500 },
        #{ name: "sand_bank", yields: "sand", regrow: 2.0, max: 10.0, ground: ["sand"], gather_ms: 2000 },
        #{ name: "peat_bank", yields: "peat", regrow: 0.15, max: 12.0, ground: ["grass", "dirt"], gather_ms: 5000 },
        #{ name: "root_plot", yields: "roots", regrow: 0.4, max: 6.0, ground: ["dirt", "grass"], gather_ms: 3000 },
        #{ name: "greens_bed", yields: "greens", regrow: 0.5, max: 4.0, ground: ["grass"], gather_ms: 2000 },
        // A fish trap in the shallows.
        #{ name: "weir", yields: "fish", regrow: 1.0, max: 4.0, ground: ["sand"], by_water: true, gather_ms: 4000 },
    ]
}

fn know_how() {
    base_know_how() + [
        #{ name: "glassmaking", help: "melt ash and sand into glass at a burning furnace", requires: ["fire"] },
    ]
}

fn recipes() {
    [
        #{ name: "ash", at: "fire", lit: true, takes: #{ kelp: 4 }, ms: 6000 },
        #{ name: "glass", at: "furnace", lit: true, takes: #{ alkali: 1, sand: 2 }, fuel: 1.0, knows: "glassmaking", ms: 15000 },
        #{ name: "smoking", turns: "smokes_to", at: "smokehouse", lit: true, fuel: 0.5, knows: "smoking", ms: 10000 },
        #{ name: "baking", turns: "bakes_to", at: "oven", lit: true, fuel: 0.25, ms: 6000 },
        #{ name: "lamp_oil", at: "fire", lit: true, takes: #{ fish: 2 }, ms: 8000 },
    ]
}
