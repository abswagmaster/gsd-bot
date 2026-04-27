import os
import re
import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv
from datetime import date, time
from zoneinfo import ZoneInfo
import sync
import gsd

sync.ensure_clone()

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD = discord.Object(id=1447801728366809160)
REMINDER_CHANNEL_ID = 1447801771949953206
LOCAL_TZ = ZoneInfo("America/New_York")  # Eastern Time

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


def _person_name(interaction: discord.Interaction) -> str:
    return interaction.user.display_name


def _fmt_section(lines: list[str], label: str, emoji: str, start_n: int) -> str:
    rows = []
    n = start_n
    for line in lines:
        if re.match(r"\s*- \[.\]", line):
            text = re.sub(r"\s*- \[.\]\s*", "", line).strip()
            done = bool(re.match(r"\s*- \[x\]", line, re.IGNORECASE))
            checkbox = "☑" if done else "☐"
            rows.append(f"`{n}.` {checkbox} {text}")
            n += 1
    if not rows:
        return f"**{emoji} {label}**\n*nothing here*"
    return f"**{emoji} {label}**\n" + "\n".join(rows)


def _person_embed(person: str, sections: dict, color: discord.Color) -> discord.Embed:
    tasks = gsd.all_tasks(sections)
    ns_count = sum(1 for k, _, _ in tasks if k == "no_sleep")
    ns_text = _fmt_section(sections["no_sleep"], "No Sleep", "🔥", 1)
    be_text = _fmt_section(sections["best_effort"], "Best Effort", "⚡", ns_count + 1)
    embed = discord.Embed(title=person, description=f"{ns_text}\n\n{be_text}", color=color)
    return embed


PERSON_COLORS = [discord.Color.blurple(), discord.Color.og_blurple()]


def _build_all_lists_embeds() -> list[discord.Embed]:
    people = gsd.list_people()
    if not people:
        return []
    embeds = []
    for i, person in enumerate(people):
        sections = gsd.read_tasks(person)
        color = PERSON_COLORS[i % len(PERSON_COLORS)]
        embeds.append(_person_embed(person, sections, color))
    embeds[0].title = f"📋 {date.today().isoformat()} — {embeds[0].title}"
    return embeds


@tasks.loop(time=[time(10, 0, tzinfo=LOCAL_TZ), time(23, 0, tzinfo=LOCAL_TZ)])
async def daily_reminder():
    channel = client.get_channel(REMINDER_CHANNEL_ID)
    if channel is None:
        print(f"Reminder channel {REMINDER_CHANNEL_ID} not found")
        return
    embeds = _build_all_lists_embeds()
    if not embeds:
        await channel.send("📋 Daily reminder — no tasks yet today.")
        return
    now = discord.utils.utcnow().astimezone(LOCAL_TZ)
    header = "🌅 Morning check-in" if now.hour < 12 else "🌙 Evening check-in"
    await channel.send(content=header, embeds=embeds)


@daily_reminder.before_loop
async def _before_reminder():
    await client.wait_until_ready()


@client.event
async def on_ready():
    tree.copy_global_to(guild=GUILD)
    await tree.sync(guild=GUILD)
    if not daily_reminder.is_running():
        daily_reminder.start()
    print(f"Logged in as {client.user} — synced to guild, reminder loop started")


def _build_one_list_embed(person: str) -> discord.Embed:
    sections = gsd.read_tasks(person)
    embed = _person_embed(person, sections, PERSON_COLORS[0])
    embed.title = f"📋 {date.today().isoformat()} — {embed.title}"
    return embed


@tree.command(name="list", description="Show your own tasks for today")
async def cmd_list(interaction: discord.Interaction):
    person = _person_name(interaction)
    await interaction.response.send_message(embed=_build_one_list_embed(person))


@tree.command(name="listboth", description="Show today's tasks for both people")
async def cmd_listboth(interaction: discord.Interaction):
    embeds = _build_all_lists_embeds()
    if not embeds:
        await interaction.response.send_message("No tasks yet. Use `/nosleep` or `/effort` to add some.", ephemeral=True)
        return
    await interaction.response.send_message(embeds=embeds)


@tree.command(name="nosleep", description="Add one or more tasks to your No Sleep list (separate with commas)")
@app_commands.describe(tasks="e.g. finish report, call Alex, review PR")
async def cmd_nosleep(interaction: discord.Interaction, tasks: str):
    person = _person_name(interaction)
    items = [t.strip() for t in tasks.split(",") if t.strip()]
    for item in items:
        gsd.add_task(person, item, "no_sleep")
    lines = "\n".join(f"☐ {item}" for item in items)
    embed = discord.Embed(
        description=f"🔥 **No Sleep** added for **{person}**\n{lines}",
        color=discord.Color.red()
    )
    await interaction.response.send_message(embed=embed)


@tree.command(name="effort", description="Add one or more tasks to your Best Effort list (separate with commas)")
@app_commands.describe(tasks="e.g. clean inbox, update docs, review metrics")
async def cmd_effort(interaction: discord.Interaction, tasks: str):
    person = _person_name(interaction)
    items = [t.strip() for t in tasks.split(",") if t.strip()]
    for item in items:
        gsd.add_task(person, item, "best_effort")
    lines = "\n".join(f"☐ {item}" for item in items)
    embed = discord.Embed(
        description=f"⚡ **Best Effort** added for **{person}**\n{lines}",
        color=discord.Color.yellow()
    )
    await interaction.response.send_message(embed=embed)


def _parse_numbers(s: str) -> list[int]:
    """Parse '1,2,3' or '1 2 3' or '1, 2, 3' into a sorted unique list of ints."""
    parts = re.split(r"[\s,]+", s.strip())
    nums = []
    for p in parts:
        if p.isdigit():
            nums.append(int(p))
    # Sort descending so we toggle highest indices first (numbering stays stable)
    return sorted(set(nums), reverse=True)


@tree.command(name="done", description="Mark one or more of your tasks as complete")
@app_commands.describe(numbers="Task number(s), e.g. 1 or 1,2,3")
async def cmd_done(interaction: discord.Interaction, numbers: str):
    person = _person_name(interaction)
    nums = _parse_numbers(numbers)
    if not nums:
        await interaction.response.send_message("No valid task numbers given.", ephemeral=True)
        return
    completed: list[tuple[str, str]] = []
    missing: list[int] = []
    for n in nums:
        result = gsd.toggle_task(person, n, done=True)
        if result is None:
            missing.append(n)
        else:
            completed.append(result)
    lines = []
    for section, text in completed:
        emoji = "🔥" if section == "no_sleep" else "⚡"
        lines.append(f"{emoji} ☑ ~~{text}~~")
    if missing:
        lines.append(f"\n*Skipped (not found):* {', '.join(f'#{n}' for n in sorted(missing))}")
    embed = discord.Embed(
        title=f"Done — {person}",
        description="\n".join(lines) if lines else "Nothing to do.",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)


@tree.command(name="undone", description="Reopen one or more of your completed tasks")
@app_commands.describe(numbers="Task number(s), e.g. 1 or 1,2,3")
async def cmd_undone(interaction: discord.Interaction, numbers: str):
    person = _person_name(interaction)
    nums = _parse_numbers(numbers)
    if not nums:
        await interaction.response.send_message("No valid task numbers given.", ephemeral=True)
        return
    reopened: list[tuple[str, str]] = []
    missing: list[int] = []
    for n in nums:
        result = gsd.toggle_task(person, n, done=False)
        if result is None:
            missing.append(n)
        else:
            reopened.append(result)
    lines = []
    for section, text in reopened:
        emoji = "🔥" if section == "no_sleep" else "⚡"
        lines.append(f"{emoji} ☐ {text}")
    if missing:
        lines.append(f"\n*Skipped (not found):* {', '.join(f'#{n}' for n in sorted(missing))}")
    embed = discord.Embed(
        title=f"Reopened — {person}",
        description="\n".join(lines) if lines else "Nothing to do.",
        color=discord.Color.orange()
    )
    await interaction.response.send_message(embed=embed)


@tree.command(name="clear", description="Remove all your completed tasks")
async def cmd_clear(interaction: discord.Interaction):
    person = _person_name(interaction)
    count = gsd.clear_done(person)
    embed = discord.Embed(
        description=f"Cleared **{count}** completed task(s) for **{person}**.",
        color=discord.Color.greyple()
    )
    await interaction.response.send_message(embed=embed)


client.run(TOKEN)
