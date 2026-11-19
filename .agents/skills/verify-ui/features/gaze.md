# Zoom-linked gaze

In a gaze-enabled world, roll the wheel over the world or pinch with the north-up camera. The zoom target selects Far, Middle or Near with 0.025 hysteresis at 0.275 and 0.775. Camera height and pitch still ease using the chosen preset. Orbit keeps the north-up camera's last gaze intent.

The player connection keeps the newest target while a request is in flight or cooling down. It waits for its own `my_senses_v_2` row after a reconnect. Shade uses the radius and mask for the confirmed field together. With gaze off, Shade uses the original senses feed.

## Drive

```sh
.agents/skills/verify-ui/scripts/check.py --run "$R" gaze
```

Use a doctored Cullet scratch world with the terrain-fitted Cullet kit. The scenario enables gaze through `set_world_law`, selects the three stops on Ours, fixed 58°, and samples visible and hidden targets. It drives six opposite wheel inputs in under a second, disconnects the player's socket while changing zoom, and repeats the three stops with `cover_sight_on` and `cover_brush_on` at the authored hedge. The driver restores the scratch laws and epoch when finished.

Read `ui/gaze/gaze-proof.json` for the four assertions' inputs and outcomes, `scene.json` for the player-scoped SQL and admin fixture calls, and `fields/` for the masks and their numeric parameters. The Shade trace in `client.log` records each frame's applied band, drawn band, rendered radius, mask revision and shader mode. Still images show both fixtures at each stop. Gaze-off comparisons use the legacy owner view before and after enabling gaze.

Code entry points are `camera::follow`, `Net::update_gaze`, `sightedge::update`, `sightedge::shade` and `sightfield::update`.
