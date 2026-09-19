# Release validation

Run the distribution validator against the complete candidate files **before**
pushing to `main` or uploading public release assets. Consumers read `main`
directly. A check triggered after a push is a detection mechanism, not a
publication gate. The ESPHome deploy job runs this check before publication.
The HomeKit and Matter producer workflows also invoke it before committing
their candidate files, and again after each rebase before retrying a push.
Their GitHub Release jobs depend on successful deployment, so validation or
push failure also blocks release asset uploads. Link's `tools/publish_fw.py
--distribution <checkout>` runs the same validator against a temporary complete
candidate tree before replacing the local plaintext channel. It never pushes;
run the validator again immediately before publication and after any rebase.

## ESPHome pull-request gate

The ESPHome workflow builds both supported boards for every pull request whose
base is `main`, including documentation-only changes. PR triggers intentionally
have no path filter: a filtered-out workflow can leave a required check pending.
The stable check name is **ESPHome validation**. It runs after the matrix even
when a build fails, and explicitly fails on failed, cancelled, or skipped builds.
This follows GitHub's [required-check guidance](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks).

The validation job assembles the manifest from both build artifacts, validates
the complete candidate distribution tree, and uploads `validated-esphome`.
Build and validation jobs have read-only repository permissions and do not
persist checkout credentials. A separate publication job requests an App token
with write access only for successful push or manual runs on `refs/heads/main`.
It downloads the validated artifact from that same workflow run, revalidates
the candidate, and retains validation after each rebase. PRs and manual runs on
other branches cannot enter this job. Concurrency is separate for each PR and
for each branch; new PR commits cancel only that PR's previous run, while
`main` runs serialize.

The workflow alone does not prevent a merge or a direct push. The active
[Firmware publication gate](https://github.com/Serin-Labs/serin-cn105/rules/23711012)
ruleset was enabled on 2026-09-19 after successful App-authenticated publication
from ESPHome, HomeKit and Matter. It requires **ESPHome validation** from the
GitHub Actions App, requires the PR to be current with `main`, and blocks force
pushes and deletion of `main`. Only Serin Firmware Publisher has an **Always
allow** bypass for its validated generated commits.

To restore this enforcement in another repository or after a settings reset:

1. Run a PR targeting `main` and confirm `ESPHome validation` succeeds. Also
   confirm that its publication job is skipped.
2. Make **ESPHome validation** from GitHub Actions a required status check for
   `main`. Require the PR to be current with `main` so the checked merge result
   includes the latest configuration. If merge queues are introduced, add the
   `merge_group` workflow trigger before requiring this check in the queue.
3. Add **Serin Firmware Publisher** to the ruleset bypass list with **Always
   allow**, so ESPHome, HomeKit and Matter can push generated distribution
   commits. Their commits cannot receive checks until after publication. Deploy
   and verify the App-token workflow changes in all three repositories before
   activating the rule. Keep pre-push validation enabled for these publishers.
   Use a reviewed PR for manually staged Link releases so a human bypass is not
   needed.

These repository settings are a separate rollout step; local workflow edits do
not enable them. To check workflow policy locally with Node 24, install the two
test-only dependencies outside the checkout, then run the real Actions
expressions and shell gates against allowed and denied events:

```bash
workflow_check_dir="$(mktemp -d -t serin-workflow-check.XXXXXX)"
npm install --prefix "$workflow_check_dir" --ignore-scripts --no-audit --no-fund \
  @actions/expressions@0.3.61 yaml@2.9.1
WORKFLOW_TEST_MODULES="$workflow_check_dir/node_modules" \
  node scripts/check-esphome-workflow.mjs
```

## Publisher authentication

ESPHome, HomeKit and Matter authenticate distribution pushes with the private
**Serin Firmware Publisher** GitHub App (`serin-firmware-publisher`), installed
on `Serin-Labs/serin-cn105` only. Configure these Actions values in each producer
repository: `Serin-Labs/serin-cn105`, `akifbayram/mitsubishi-cn105-homekit`, and
`akifbayram/mitsubishi-cn105-matter`.

| Actions setting | Value |
| --- | --- |
| Variable `SERIN_PUBLISHER_CLIENT_ID` | The App's Client ID |
| Secret `SERIN_PUBLISHER_PRIVATE_KEY` | The complete downloaded PEM private key |

Only the guarded deployment job invokes the pinned
[`actions/create-github-app-token`](https://github.com/actions/create-github-app-token)
action. It requests `contents: write` for `Serin-Labs/serin-cn105` and supplies
the installation token to checkout. The action revokes the token when the job
ends; tokens otherwise expire after one hour. The job's default `GITHUB_TOKEN`
retains read access. Source-repository release uploads keep their own existing
`GITHUB_TOKEN` permissions.

App-authenticated pushes trigger distribution validation, including ESPHome's
generated firmware commits. ESPHome's build trigger excludes `firmware/**`, so
these commits do not start another firmware build. The old `SERIN_CN105_PAT`
secrets were removed from both external producer repos on 2026-09-19 after
successful hosted publication. All three publishers revoked their installation
tokens at job completion, and their App pushes triggered successful follow-up
manifest validation. Secret configuration and local authentication tests alone
do not establish these hosted results.

## Rollout order

Land this repo's validator, `scripts/requirements-validation.txt`, pinned public
key and legacy artifact index on `main` first. Then land the HomeKit and Matter
workflow changes. Those workflows install validation tools from their
distribution checkout; missing tools stop the job rather than bypassing the
check. Their host-test CI pins an immutable validator revision that has been landed
on `main`.

The producer workflows permit publication only from version tags (`v*`).
Manual branch runs build downloadable artifacts without publishing. Pushes
get at most three attempts; a failed rebase or validation stops immediately.
Rerunning an unchanged, valid release does not require a new distribution
commit.

The Matter workflow routes stable tags to `firmware/matter/` and prerelease
tags to `firmware/matter/beta/`, with matching `channel` metadata. Each channel
preserves the other's files. Only the newest beta is kept, and both channels
use the same validation gate before publication.

## Link plaintext OTA migration

The public plaintext feeds use `firmware/link/ota/stable/manifest.json` and
`firmware/link/ota/beta/manifest.json`. Both reference signed app images for
`link15` and `link21` beside the manifest. The Link publisher stages both boards
and the selected channel with `--distribution <serin-cn105 checkout>`; it rejects
development mode, factory mode and partial board sets for this operation.
New manifests omit private source-repo release links.

Preserve `firmware/link/manifest.json`, `firmware/link/beta/manifest.json` and
their encrypted files byte for byte. The validator requires the archived
encrypted format at those paths and plaintext at the new paths; it also checks
that channel metadata matches the directory. A valid signature does not make
plaintext compatible with an encrypted updater.

Roll out the validator first, then the producer changes. Build and stage the
intended releases, review them, and validate the complete checkout before
pushing. Confirm public HTTPS access to both manifests and every referenced
image before shipping firmware with the new defaults. Source changes alone do
not create live feeds. The firmware source repo's private release URLs are not
a public distribution mechanism.

Installed plaintext builds can select the new public feed through `ota-url`
over USB, provided they trust the production key. New firmware defaults do not
replace saved URL overrides. Installed encrypted builds need a new USB factory
image containing the new updater and URLs; the current archived images are
not that migration. Stage and validate new factory images separately. No
encrypted bridge release is generated by this migration.

Current Link tooling names factory images `serin_link_<board>_factory.bin`;
the published 0.1.6 images use the retired `serin_dial_` prefix. Copy the new
`factory-manifest.json` and both images into `firmware/link/` and `git rm` the
`serin_dial_*_factory.bin` files in the same commit. The web installer follows
the manifest's paths, so the rename needs no installer change.

## Running validation

Use Python 3.12 or newer in a virtual environment:

```bash
python -m pip install -r scripts/requirements-validation.txt
python -m unittest discover -s scripts -p 'test_*.py'
python scripts/validate-manifests.py
```

The last command validates all `manifest.json` and `factory-manifest.json`
files below `firmware/`. It returns a nonzero status if any manifest fails.
A `.bin` under `firmware/link/` that no manifest references also fails, because
Link files are copied in by hand and a leftover one stays downloadable.
Elsewhere, unreferenced files only warn.
No firmware files or manifests are modified. Run it again if a rebase changes
the candidate tree before a push.

To check staged files from another producer, give explicit manifests. Paths
inside each manifest are resolved relative to that manifest's directory:

```bash
python /path/to/serin-cn105/scripts/validate-manifests.py \
    /path/to/serin-link/dist/stable/manifest.json \
    /path/to/serin-link/dist_factory/factory-manifest.json
```

Explicit arguments validate only those manifests, so an unrelated product in
the distribution checkout does not block inspection of a staged release.
The producer must still validate the complete candidate distribution checkout
before pushing files into it.

## Contracts

All manifests need a nonempty name, a version of the form
`maj.min.patch[-pre.N]` (at most 31 ASCII characters), and a nonempty builds
array. Beta versions require `channel: beta`; stable versions use `stable` or
omit the field. A supplied `release_url` must be HTTPS. Duplicate JSON keys,
duplicate boards, unsafe paths, missing or empty files, and mixed manifest
formats fail validation. Relative paths cannot traverse parent directories,
contain URL query/fragment syntax, or resolve through symlinks outside the
manifest directory.

| Format | Required build fields | Artifact checks |
| --- | --- | --- |
| ESP Web Tools | `board`, `chipFamily`, app `sha256`, nonempty `parts` of `{path, offset, sha256}` | Board/family match; sector-aligned, nonoverlapping parts within board flash capacity; SHA-256 of every part and of the app |
| Link plaintext OTA | `board` (`link15`/`link21`), `path`, `size`, `sha256` | Actual size and hash; valid ESP32-S3 image; first RSA signature matches the pinned production key; embedded version matches the manifest; fits a 4 MiB OTA slot |
| Link factory | `board` (`viewe15`/`viewe21`), `path`, `size`, `sha256` | Actual size and hash; bootloader image checksums; partition-table checksum and exact supported layout; signed app at `0x20000` with matching version |
| Archived Link encrypted OTA | Link OTA fields plus `enc_size` | Exact archived version/build metadata, ciphertext size and ciphertext SHA-256 |

Factory manifests also require a boolean `dirty` field. Publication checks
reject `dirty: true`. `--allow-dirty` permits local inspection of such a build
while retaining the other checks and printing a warning; never use it in a
publication job. The dirty flag is a producer assertion, not independently
verifiable build provenance.

The supported factory partition layout is the current Link `partitions.csv`:
NVS at `0x9000` (size `0x6000`), OTA data at `0xf000` (`0x2000`), PHY at
`0x11000` (`0x1000`), and two 4 MiB OTA slots at `0x20000` and `0x420000`.
Partition types, subtypes, flags and names must also match. A layout migration
needs a coordinated validator and firmware change. The format is documented
by Espressif in [partition tables](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32s3/api-guides/partition-tables.html)
and [application images](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32s3/api-reference/system/app_image_format.html).

## Trust and legacy compatibility

[`scripts/keys/serin-link-release.pub`](../scripts/keys/serin-link-release.pub)
is the same public key pinned by `serin-link/tools/keys/serin-link-release.pub`.
It was verified against both published 0.1.6 factory images on 2026-09-18.
Its DER SubjectPublicKeyInfo SHA-256 fingerprint is:

```text
935cd0d3f264367edee4933c85172a41ff1f0be63a889bcdb9a0b7aee960f14d
```

Tests use disposable private keys. Validation needs only the production
public key. Changing this pin does not rotate trust on installed devices.

[`scripts/legacy-link-artifacts.json`](../scripts/legacy-link-artifacts.json)
records the three existing encrypted artifacts: both stable 0.1.6 boards and
the 0.1.7-beta.1 Link 1.5 image. Their bytes and metadata were recorded from
distribution commit `d274383a8c4f73da56559dc38891257ca6ff7dc9` on 2026-09-18.
This record detects changes to those archived artifacts; it does not prove
their plaintext hashes, signatures or embedded versions. The validator says
so in its output. Adding `enc_size` to a new file cannot bypass the signature
check because the file must match this archive exactly. New Link releases
use signed plaintext. Do not regenerate the archive to make a changed image
pass validation.

Every multipart controller build requires a SHA-256 for each part, including
the bootloader, partition table and OTA-data image. The build-level hash stays
the app hash for device OTA compatibility. A single merged image can use only
its build-level hash; if a part hash is supplied, that hash is checked too.
Deploy updated producer workflows before enforcing this contract. Generate
part hashes for existing published files, validate the full distribution, and
confirm the public mirror serves those manifests before deploying the strict
browser check. No firmware bytes or release versions change in that migration.

These checks do not establish physical board identity from a signed app,
prove bootloader/app compatibility, perform a hardware boot test, or validate
network availability of update URLs.

For this rollout, physical acceptance is limited to Link 1.5 and NanoC6.
Link 2.1 and AtomS3 Lite receive build and automated checks only, by the
maintainer's decision. Do not describe those boards as hardware-qualified.
