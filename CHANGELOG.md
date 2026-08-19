# Changelog

## [0.2.0](https://github.com/srobroek/sabot/compare/v0.1.0...v0.2.0) (2026-08-19)


### Features

* **sabot:** bake base-extras, and add the rust-extras, heavy, scanners, and generator surfaces ([#29](https://github.com/srobroek/sabot/issues/29)) ([792be13](https://github.com/srobroek/sabot/commit/792be139dff79699496c0466f1ac4bfd9fcef5ca))


### Bug Fixes

* **sabot/base:** symlink rg to ripgrep so the tool probe answers ([0949cf1](https://github.com/srobroek/sabot/commit/0949cf193bfc6c8e1e3dac43d0a02586c03b2fb2))
* **sabot:** bake offline vuln DBs, rule packs, and fuzz deps into surface images ([#25](https://github.com/srobroek/sabot/issues/25)) ([d6dea76](https://github.com/srobroek/sabot/commit/d6dea76f35d1f803e0ab8893fefc28878d6c6c26))
* **sabot:** first-class writable-source build recipe (--copy-src, --scratch) ([#23](https://github.com/srobroek/sabot/issues/23)) ([ac109a8](https://github.com/srobroek/sabot/commit/ac109a8c627cbbbc61fb0af5f8cc66a05d12ca32))
* **sabot:** make the container execution path actually run a cargo campaign ([#21](https://github.com/srobroek/sabot/issues/21)) ([164855e](https://github.com/srobroek/sabot/commit/164855efb925dd53ba363dcd674ce926519d9ab2))
* **sabot:** make the python and node surfaces ship working fuzzers (bs-156) ([#27](https://github.com/srobroek/sabot/issues/27)) ([7e34155](https://github.com/srobroek/sabot/commit/7e34155f7615e19c162394d96924a595cad96ab8))


### Documentation

* **sabot:** correct detect-stacks.py --json drift to real interface ([#22](https://github.com/srobroek/sabot/issues/22)) ([eb97145](https://github.com/srobroek/sabot/commit/eb971454839e59cd85284cb375e0bd398fa7c0a1))
* **sabot:** tool coverage matrix — 57 tools, offline requirement, bake status ([#24](https://github.com/srobroek/sabot/issues/24)) ([ad8ff21](https://github.com/srobroek/sabot/commit/ad8ff215105bcca32d4023a0dfae46811a6516a0))

## [0.1.0](https://github.com/srobroek/break-stuff/compare/sabot-marketplace--v0.1.0...sabot-marketplace--v0.1.0) (2026-08-17)


### ⚠ BREAKING CHANGES

* rename break-stuff to sabot (package/repo) + sabotage (skill) ([#11](https://github.com/srobroek/break-stuff/issues/11))

### Features

* **break-stuff:** interview-by-default, agentic-code recon, delegate provisioning ([#10](https://github.com/srobroek/break-stuff/issues/10)) ([dae4b75](https://github.com/srobroek/break-stuff/commit/dae4b755b99caca45bb8e9b3d39c4b8c896c48d1))
* generate both marketplaces + release-please, add README ([e65b95d](https://github.com/srobroek/break-stuff/commit/e65b95dade30fd8c0fe7960c8f26ecfdd727cb0f))


### Refactors

* rename break-stuff to sabot (package/repo) + sabotage (skill) ([#11](https://github.com/srobroek/break-stuff/issues/11)) ([6eede11](https://github.com/srobroek/break-stuff/commit/6eede11ee046d646d39855f30442d4c46c9af64c))


### Documentation

* real README — usage, agent chain, correct dual-marketplace install ([638a8ae](https://github.com/srobroek/break-stuff/commit/638a8ae2fc453df2f2a6da018872bda659fedf91))
