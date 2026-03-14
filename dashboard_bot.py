"""
Vinted Dashboard Bot
====================
A Discord bot that provides a button-based control panel
to manage Vinted alert searches. Runs 24/7 on Railway.

Environment variables needed (set in Railway):
    DISCORD_BOT_TOKEN   — your Discord bot token
    GITHUB_TOKEN        — GitHub personal access token (repo scope)
    GITHUB_USERNAME     — HobGoblin-0930
    GITHUB_REPO         — vinted-bot
"""

import os
import json
import base64
import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput
import aiohttp

# ──────────────────────────────────────────────
#  CONFIG
# ──────────────────────────────────────────────
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
GITHUB_TOKEN      = os.environ.get("GITHUB_TOKEN", "")
GITHUB_USERNAME   = os.environ.get("GITHUB_USERNAME", "HobGoblin-0930")
GITHUB_REPO       = os.environ.get("GITHUB_REPO", "vinted-bot")
SEARCHES_FILE     = "vinted_searches.json"

GITHUB_API = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{SEARCHES_FILE}"
GITHUB_HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}

COLOURS = [0x09B1BA, 0xF5A623, 0x7ED321, 0xD0021B, 0x9B59B6, 0x3498DB]

CONDITION_NAMES = {
    1: "New w/o tags",
    2: "Very good",
    3: "Good",
    4: "Satisfactory",
    6: "New with tags",
}

# ──────────────────────────────────────────────
#  GITHUB HELPERS
# ──────────────────────────────────────────────

async def load_searches():
    async with aiohttp.ClientSession() as session:
        async with session.get(GITHUB_API, headers=GITHUB_HEADERS) as r:
            if r.status == 404:
                return [], ""
            data = await r.json()
            content = base64.b64decode(data["content"].replace("\n", "")).decode("utf-8")
            return json.loads(content), data["sha"]


async def save_searches(searches: list, sha: str):
    content = base64.b64encode(json.dumps(searches, indent=2).encode()).decode()
    body = {
        "message": "Update searches via Discord dashboard",
        "content": content,
    }
    if sha:
        body["sha"] = sha

    async with aiohttp.ClientSession() as session:
        async with session.put(GITHUB_API, headers=GITHUB_HEADERS, json=body) as r:
            data = await r.json()
            if r.status not in (200, 201):
                raise Exception(f"GitHub save failed: {data.get('message', r.status)}")
            return data["content"]["sha"]


# ──────────────────────────────────────────────
#  BOT SETUP
# ──────────────────────────────────────────────

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


# ──────────────────────────────────────────────
#  VIEWS
# ──────────────────────────────────────────────

class ControlPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="➕ Add Search", style=discord.ButtonStyle.success, custom_id="cp_add")
    async def add_search(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(AddSearchModal())

    @discord.ui.button(label="📋 List Searches", style=discord.ButtonStyle.primary, custom_id="cp_list")
    async def list_searches(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        searches, _ = await load_searches()
        if not searches:
            await interaction.followup.send("No searches configured yet. Click **➕ Add Search** to get started!", ephemeral=True)
            return
        view = SearchListView(searches)
        embed = build_list_embed(searches)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="🔄 Refresh Panel", style=discord.ButtonStyle.secondary, custom_id="cp_refresh")
    async def refresh_panel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        searches, _ = await load_searches()
        embed = build_panel_embed(searches)
        await interaction.message.edit(embed=embed, view=ControlPanelView())
        await interaction.followup.send("✅ Panel refreshed!", ephemeral=True)


class SearchListView(View):
    def __init__(self, searches):
        super().__init__(timeout=120)
        self.searches = searches
        for i, s in enumerate(searches):
            self.add_item(SearchActionButton(i, s))


class SearchActionButton(Button):
    def __init__(self, index: int, search: dict):
        label = search["label"][:20]
        enabled = search.get("enabled", True)
        toggle_label = "⏸" if enabled else "▶️"
        super().__init__(
            label=f"{toggle_label} {label}",
            style=discord.ButtonStyle.success if enabled else discord.ButtonStyle.secondary,
            custom_id=f"search_{index}",
            row=index % 4,
        )
        self.index = index
        self.search = search

    async def callback(self, interaction: discord.Interaction):
        view = SearchDetailView(self.index, self.search)
        embed = build_detail_embed(self.search)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class SearchDetailView(View):
    def __init__(self, index: int, search: dict):
        super().__init__(timeout=120)
        self.index = index
        self.search = search
        enabled = search.get("enabled", True)
        self.toggle_btn.label = "⏸ Disable" if enabled else "▶️ Enable"
        self.toggle_btn.style = discord.ButtonStyle.secondary if enabled else discord.ButtonStyle.success

    @discord.ui.button(label="✏️ Edit", style=discord.ButtonStyle.primary)
    async def edit_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(EditSearchModal(self.index, self.search))

    @discord.ui.button(label="⏸ Disable", style=discord.ButtonStyle.secondary)
    async def toggle_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        searches, sha = await load_searches()
        if self.index < len(searches):
            searches[self.index]["enabled"] = not searches[self.index].get("enabled", True)
            await save_searches(searches, sha)
            status = "enabled ✅" if searches[self.index]["enabled"] else "disabled ⏸"
            await interaction.followup.send(f"**{searches[self.index]['label']}** is now {status}", ephemeral=True)

    @discord.ui.button(label="🗑️ Delete", style=discord.ButtonStyle.danger)
    async def delete_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        searches, sha = await load_searches()
        if self.index < len(searches):
            name = searches[self.index]["label"]
            searches.pop(self.index)
            await save_searches(searches, sha)
            await interaction.followup.send(f"🗑️ **{name}** has been deleted.", ephemeral=True)


# ──────────────────────────────────────────────
#  MODALS
# ──────────────────────────────────────────────

class AddSearchModal(Modal, title="➕ Add New Search"):
    label_input = TextInput(label="Label (nickname)", placeholder="e.g. Xbox Controller", max_length=50)
    keywords    = TextInput(label="Search Keywords", placeholder="e.g. xbox controller")
    max_price   = TextInput(label="Max Price (£) — leave blank for any", placeholder="e.g. 15", required=False)
    min_price   = TextInput(label="Min Price (£) — leave blank for any", placeholder="e.g. 5", required=False)
    conditions  = TextInput(
        label="Conditions (comma separated numbers)",
        placeholder="1=No tags, 2=V.Good, 3=Good, 4=OK, 6=With tags",
        default="1,2,3,4",
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        searches, sha = await load_searches()

        max_p = float(self.max_price.value) if self.max_price.value.strip() else None
        min_p = float(self.min_price.value) if self.min_price.value.strip() else None

        try:
            status_ids = [int(x.strip()) for x in self.conditions.value.split(",") if x.strip()]
        except ValueError:
            status_ids = [1, 2, 3, 4]

        searches.append({
            "label": self.label_input.value.strip(),
            "search_text": self.keywords.value.strip(),
            "max_price": max_p,
            "min_price": min_p,
            "size_ids": [],
            "brand_ids": [],
            "status_ids": status_ids,
            "order": "newest_first",
            "enabled": True,
        })

        await save_searches(searches, sha)
        await interaction.followup.send(
            f"✅ **{self.label_input.value.strip()}** added! The bot will start alerting on new listings.",
            ephemeral=True
        )


class EditSearchModal(Modal, title="✏️ Edit Search"):
    def __init__(self, index: int, search: dict):
        super().__init__()
        self.index = index
        self.label_input = TextInput(label="Label", default=search.get("label", ""), max_length=50)
        self.keywords    = TextInput(label="Search Keywords", default=search.get("search_text", ""))
        self.max_price   = TextInput(label="Max Price (£) — leave blank for any",
                                     default=str(search["max_price"]) if search.get("max_price") else "",
                                     required=False)
        self.min_price   = TextInput(label="Min Price (£) — leave blank for any",
                                     default=str(search["min_price"]) if search.get("min_price") else "",
                                     required=False)
        cond_default = ",".join(str(x) for x in search.get("status_ids", [1,2,3,4]))
        self.conditions = TextInput(
            label="Conditions (1=No tags, 2=V.Good, 3=Good, 4=OK, 6=With tags)",
            default=cond_default,
            required=False,
        )
        self.add_item(self.label_input)
        self.add_item(self.keywords)
        self.add_item(self.max_price)
        self.add_item(self.min_price)
        self.add_item(self.conditions)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        searches, sha = await load_searches()

        max_p = float(self.max_price.value) if self.max_price.value.strip() else None
        min_p = float(self.min_price.value) if self.min_price.value.strip() else None

        try:
            status_ids = [int(x.strip()) for x in self.conditions.value.split(",") if x.strip()]
        except ValueError:
            status_ids = [1, 2, 3, 4]

        if self.index < len(searches):
            searches[self.index].update({
                "label": self.label_input.value.strip(),
                "search_text": self.keywords.value.strip(),
                "max_price": max_p,
                "min_price": min_p,
                "status_ids": status_ids,
            })
            await save_searches(searches, sha)
            await interaction.followup.send(f"✅ **{self.label_input.value.strip()}** updated!", ephemeral=True)


# ──────────────────────────────────────────────
#  EMBEDS
# ──────────────────────────────────────────────

def build_panel_embed(searches: list) -> discord.Embed:
    active   = sum(1 for s in searches if s.get("enabled", True))
    inactive = len(searches) - active

    embed = discord.Embed(
        title="🛍 Vinted Alert Dashboard",
        description="Manage your Vinted searches below. New listings that match will be posted in this channel automatically.",
        color=0x09B1BA,
    )

    if searches:
        lines = []
        for s in searches:
            enabled = s.get("enabled", True)
            icon    = "🟢" if enabled else "⭕"
            price   = f"£{s['max_price']}" if s.get("max_price") else "any price"
            lines.append(f"{icon} **{s['label']}** — {s['search_text']} | max {price}")
        embed.add_field(name="Active Searches", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="Active Searches", value="None yet — click ➕ Add Search to get started!", inline=False)

    embed.add_field(name="🟢 Enabled",  value=str(active),   inline=True)
    embed.add_field(name="⭕ Disabled", value=str(inactive),  inline=True)
    embed.add_field(name="📦 Total",    value=str(len(searches)), inline=True)
    embed.set_footer(text="Click 📋 List Searches to edit or remove individual searches")
    return embed


def build_list_embed(searches: list) -> discord.Embed:
    embed = discord.Embed(title="📋 Your Searches", color=0x09B1BA)
    for i, s in enumerate(searches):
        enabled   = s.get("enabled", True)
        price_str = f"£{s['max_price']}" if s.get("max_price") else "Any"
        conds     = ", ".join(CONDITION_NAMES.get(c, str(c)) for c in s.get("status_ids", []))
        val = (
            f"**Keywords:** {s['search_text']}\n"
            f"**Max Price:** {price_str}\n"
            f"**Conditions:** {conds or 'Any'}\n"
            f"**Status:** {'🟢 Enabled' if enabled else '⭕ Disabled'}"
        )
        embed.add_field(name=f"{i+1}. {s['label']}", value=val, inline=False)
    embed.set_footer(text="Click a search button below to edit, toggle or delete it")
    return embed


def build_detail_embed(search: dict) -> discord.Embed:
    enabled   = search.get("enabled", True)
    price_str = f"£{search['max_price']}" if search.get("max_price") else "Any"
    conds     = ", ".join(CONDITION_NAMES.get(c, str(c)) for c in search.get("status_ids", []))
    embed = discord.Embed(
        title=f"{'🟢' if enabled else '⭕'} {search['label']}",
        color=0x09B1BA if enabled else 0x5a6478,
    )
    embed.add_field(name="🔍 Keywords",  value=search["search_text"], inline=True)
    embed.add_field(name="💰 Max Price", value=price_str,             inline=True)
    embed.add_field(name="🔧 Conditions",value=conds or "Any",        inline=True)
    embed.set_footer(text="Use the buttons below to edit, toggle or delete this search")
    return embed


# ──────────────────────────────────────────────
#  BOT EVENTS
# ──────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ Vinted Dashboard Bot is online as {bot.user}")
    bot.add_view(ControlPanelView())  # re-register persistent view on restart


@bot.command(name="panel")
async def panel(ctx):
    """Send the control panel to this channel."""
    searches, _ = await load_searches()
    embed = build_panel_embed(searches)
    await ctx.send(embed=embed, view=ControlPanelView())
    try:
        await ctx.message.delete()
    except Exception:
        pass


# ──────────────────────────────────────────────
#  RUN
# ──────────────────────────────────────────────

if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN is not set!")
    else:
        bot.run(DISCORD_BOT_TOKEN)
