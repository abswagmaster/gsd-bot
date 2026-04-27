# GSD Discord Bot

A Discord bot that syncs with the [GSD](https://github.com/encore-ai-labs/gsd) macOS task app. Tasks are read/written directly from `~/.gsd/Daily/YYYY-MM-DD.md`, so anything you do in the bot instantly shows up in the GSD menu bar app and vice versa.

## Setup

### 1. Create a Discord bot
1. Go to https://discord.com/developers/applications → New Application
2. Bot → Add Bot → copy the token
3. OAuth2 → URL Generator → scopes: `bot`, `applications.commands` → permissions: `Send Messages`, `Use Slash Commands`
4. Open the generated URL to invite the bot to your server

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure
```bash
cp .env.example .env
# Edit .env and paste your bot token
```

### 4. Run
```bash
python bot.py
```

Slash commands are synced automatically on startup.

## Commands

| Command | Description |
|---|---|
| `/list` | Show today's tasks with checkboxes |
| `/add <task>` | Add a new task |
| `/done <number>` | Mark task #N as complete |
| `/undone <number>` | Reopen task #N |
| `/clear` | Remove all completed tasks |

## How it works

Tasks are stored as plain markdown at `~/.gsd/Daily/YYYY-MM-DD.md`:

```markdown
## Today
- [ ] incomplete task
- [x] completed task

## Done yesterday
- [x] carried over completed task
```

If today's file doesn't exist yet, the bot automatically carries forward any unchecked tasks from the most recent previous day (same behavior as the GSD app).
