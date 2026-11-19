# verify-core: laws-about-budget

Branch `laws-about-budget` from origin/main `540522fc`. The trial service, `scoped`, private `CARGO_TARGET_DIR`.

- **The change.** `laws_about(laws())` was asked at install under the running world's 2,000-operation cap, and returned nothing when it went over. Now it is read once while the script compiles, under the compile's 20,000 (`COMPILE_OPERATIONS`, goods-3), and kept with the script. A failure to read it is refused as such: "the world constants' words could not be read (…)". It is no longer refused as the first constant having no words.
- **`tick` on Cullet** 6/6 (`core-lab-184601`).
- **Rules test** `the_constants_words_are_read_with_the_compile_s_budget`: words that take more than 2,000 operations install, and the same words asked under the running cap fail. Words that cannot be read are refused with their own reason.
- **`just living-check`** with pipefail: exit 0 (876 s; rules tests included).
