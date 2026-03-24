# imu Bot Demo Recording Guide

Record a 30-60 second screen capture showing the imu bot triaging GitHub issues via Telegram.

## Prerequisites

1. imu bot running and connected to Telegram (TELEGRAM_BOT_TOKEN configured — see #407)
2. StrawPot running with the imu role active
3. A few untriaged issues in `strawpot/strawpot` (or a test repo)
4. Screen recording tool: QuickTime (Mac), OBS, or similar

## Demo Script

**Target length:** 30-60 seconds (shorter is better)

### Scene 1: Open Telegram (0-5s)

- Open Telegram (mobile preferred — feels more impressive)
- Navigate to the imu bot conversation

### Scene 2: Ask for untriaged issues (5-20s)

- Type: **"What issues need triage in the strawpot repo?"**
- Wait for imu to respond with a list of untriaged issues
- Pause briefly so the viewer can read the response

### Scene 3: Triage an issue (20-40s)

- Type: **"Triage the top issue -- label it as a bug and assign it to me"**
- Wait for imu to confirm execution (labels applied, assignment made)

### Scene 4: Verify on GitHub (40-55s)

- Switch to browser / GitHub app
- Open the same issue
- Show the label and assignee now applied

### Scene 5 (optional bonus): Code review (55-60s)

- Back in Telegram: **"Start a code review session for PR #xyz"**
- Show imu responding

## Recording Specs

| Setting      | Value                                            |
|------------- |------------------------------------------------- |
| Resolution   | 1080p minimum                                    |
| Format       | MP4 (primary), GIF (secondary for social embeds) |
| Audio        | None — use text overlays instead                 |
| Length        | 30-60 seconds                                    |

### Text Overlay Suggestions

Add brief captions at each transition:

1. "Messaging the imu bot from Telegram..."
2. "Bot lists untriaged GitHub issues"
3. "Asking the bot to triage an issue..."
4. "Issue labeled and assigned on GitHub"

## Output Files

Save recordings to this directory:

```
docs/assets/imu-demo-2026-03.mp4   # primary video
docs/assets/imu-demo-2026-03.gif   # social embed version
```

## If the Bot Isn't Working

If imu can't be demonstrated live:

1. Document exactly what fails (error messages, logs)
2. Create a follow-up issue with the bug report
3. Note: the demo video is critical for the Week 1 blog post — if it can't be recorded, the blog timeline slips

## Post-Recording Checklist

- [ ] Video is 30-60 seconds
- [ ] Shows full flow: Telegram message -> bot response -> GitHub issue updated
- [ ] Self-explanatory without audio (viewer understands what's happening)
- [ ] MP4 saved to `docs/assets/imu-demo-2026-03.mp4`
- [ ] GIF saved to `docs/assets/imu-demo-2026-03.gif`
- [ ] Commit the files and open a PR (or add to an existing one)
