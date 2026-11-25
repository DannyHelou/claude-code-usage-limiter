# Claude Code Usage Limiter open-source launch plan

**Goal** — Ship a Windows-first beta that someone can install, try without spending Claude quota, and remove. Then make the project findable through GitHub, web search, and Claude Code's plugin ecosystem.

**Approach** — Keep the existing Python limiter and Windows process supervision. Package them in a versioned release, validate the first-run experience with external testers, and use feedback to decide what to expand after launch.

**Product baseline** — [Current README](../../../README.md). The proposed release name is `claude-code-usage-limiter`. New installs start enabled at 90%. Plain `claude` in a configured PowerShell session and `/limiter` remain the main entry points.

## 1. Make installation reversible

- [ ] Update `install-powershell.ps1` to install versioned files under a stable per-user location such as `%LOCALAPPDATA%\ClaudeCodeUsageLimiter`. Keep runtime files and usage data in separate directories. Point the existing marked profile block at the installed launcher. Show which profile is being changed before applying the change.
- [ ] Add `uninstall-powershell.ps1` to remove only the marked profile block and installed program files. Preserve cutoff and usage data by default and document how users can delete it. Treat a previous checkout-based profile registration as an upgrade. Preserve its cutoff, enabled state, and readings, and avoid overwriting an unrelated `claude` function or alias.
- [ ] Add installer smoke tests that use temporary paths. Cover paths with spaces, installing twice, upgrading the checkout version, preserving unrelated profile content, and uninstalling twice.
- [ ] Verify in a fresh Windows account that `claude --version` still works, `/limiter` opens in a guarded interactive session, settings persist across upgrades, and the original Claude command works after uninstall. Publish only the PowerShell editions and Python versions actually tested.

**Exit condition** — A new user can install and uninstall without moving the checkout, editing their profile by hand, or losing saved settings during an upgrade.

## 2. Make the first stop easy to verify

- [ ] Add `python limiter.py demo` as a local, no-quota walkthrough. Use a temporary store and a disposable Windows process tree. Show a reading below 90%, then one at 90%. Confirm the supervisor stops the disposable process and its child, leaving the user's actual Claude sessions and settings untouched.
- [ ] Put a short demo recording, quickstart, and expected output near the top of `README.md`. Explain the first-run usage reading before the install example, and document how to refresh stale readings and resume after a cutoff. State that the launcher supervises sessions it starts, can interrupt tool commands, and sees usage only when Claude reports it.
- [ ] Add `.github/workflows/windows-ci.yml` to run `python -B -m unittest -v`, the installer smoke tests, and the offline stop demo. Cover the minimum supported Python version and one newer version. Keep the CI path independent of Claude credentials and network access to Anthropic.

**Exit condition** — Someone can see a process stop at the threshold without a Claude subscription, and CI verifies the same behavior.

## 3. Prepare the public repository and beta

- [ ] Initialize Git and review the files to be published. Exclude local usage databases, logs, credentials, and machine-specific configuration. Add `LICENSE` after the owner selects a license. MIT is a candidate for a permissive release.
- [ ] Add `CONTRIBUTING.md` with setup, test commands, and project scope. Add `CODE_OF_CONDUCT.md` and a short `SECURITY.md` with a private reporting route. Add issue prompts for Windows and PowerShell versions, Claude Code version, steps to reproduce, and redacted output.
- [ ] Set the repository description to “Stop Claude Code at a configurable subscription usage cutoff and save allowance for Claude chat.” Add `claude-code`, `rate-limit`, `cli`, `powershell`, and `windows` topics. Put requirements, supported platforms, install and uninstall commands, and limitations in plain text. Keep the demo supplementary to those instructions.
- [ ] Test the downloadable release artifact from a fresh directory. Draft a `v0.1.0-beta.1` release with installation instructions, the tested version range, and known limitations. Confirm the repository owner, license, and public visibility before publishing.
- [ ] Ask three to five Claude Code users on Windows to try the beta. Ask them to install it, open `/limiter`, run the offline demo, and uninstall. Record where they stop or need help, then fix recurring blockers.

**Exit condition** — At least two testers outside the project independently complete install, demo, and uninstall. No known issue can unexpectedly interfere with their PowerShell profile or terminate an unrelated process.

## 4. Launch and measure

- [ ] Publish `v0.1.0` with the downloadable artifact, release notes, and a link to the demo. Announce it in one or two Claude Code communities that allow project posts. Lead with the shared-usage problem and ask for specific installation feedback.
- [ ] For the first two weeks, triage install and cutoff reports. Check GitHub Insights for views, clones, and referrers. Track confirmed successful installs and repeated setup issues separately. Use those signals to decide the next release, since views and stars cannot verify a working install.
- [ ] Check GitHub and web-enabled assistants with real queries such as “stop Claude Code before it uses all my chat quota” and “Claude Code usage cutoff Windows.” Record whether the repo appears and whether the result correctly states platform support and reporting delay. Improve the README if the description is unclear.

## 5. Expand based on demand

- [ ] Try a Claude Code plugin prototype once the Windows release is stable. Verify command naming, hook behavior, and the need for the supervised launcher before deciding what to submit to Anthropic's directory.
- [ ] Consider macOS or Linux support, then other providers, based on requests from users who tried the beta. For each provider, verify that the CLI and chat share a subscription allowance and that the coding tool exposes usable percentage and reset data.

## References

- [GitHub repository search](https://docs.github.com/en/search-github/searching-on-github/searching-for-repositories) and [GitHub topics](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics)
- [Open Source Guides on finding users](https://opensource.guide/finding-users/) and [GitHub traffic insights](https://docs.github.com/en/repositories/viewing-activity-and-data-for-your-repository/viewing-traffic-to-a-repository)
- [Claude Code status line](https://code.claude.com/docs/en/statusline) and [plugin publishing](https://code.claude.com/docs/en/plugins/publish)
