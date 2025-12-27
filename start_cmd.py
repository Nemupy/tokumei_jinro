import discord
from discord.ext import commands
from discord import app_commands
import os
import random

# 環境変数の読み込み
GUILD_ID = int(os.getenv("GUILD_ID"))
CATEGORY_ID = int(os.getenv("CATEGORY_ID"))

def get_circle_num(n):
    circles = {1:"①", 2:"②", 3:"③", 4:"④", 5:"⑤", 6:"⑥", 7:"⑦", 8:"⑧", 9:"⑨", 10:"⑩",
               11:"⑪", 12:"⑫", 13:"⑬", 14:"⑭", 15:"⑮", 16:"⑯", 17:"⑰", 18:"⑱", 19:"⑲", 20:"⑳"}
    return circles.get(n, f"({n})")

class JoinView(discord.ui.View):
    def __init__(self, bot, max_players, target_user, owner):
        super().__init__(timeout=None)
        self.bot = bot
        self.max_players = max_players
        self.target_user = target_user
        self.owner = owner  # コマンド実行者
        self.players = []
        self.channels = {}

    @discord.ui.button(label="参加する", style=discord.ButtonStyle.green, custom_id="join_button")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user in self.players:
            await interaction.response.send_message("既に登録されています！", ephemeral=True)
            return
        if len(self.players) >= self.max_players:
            await interaction.response.send_message("定員に達しています。", ephemeral=True)
            return

        self.players.append(interaction.user)
        
        guild = interaction.guild
        category = guild.get_channel(CATEGORY_ID)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True)
        }

        channel = await guild.create_text_channel(name=f"匿名室-{len(self.players)}", category=category, overwrites=overwrites)
        self.channels[interaction.user.id] = channel

        embed = interaction.message.embeds[0]
        player_list = "\n".join([f"・{p.display_name}" for p in self.players])
        embed.set_field_at(0, name=f"参加者 ({len(self.players)}/{self.max_players})", value=player_list, inline=False)

        if len(self.players) >= 3:
            has_start_button = any(isinstance(item, discord.ui.Button) and item.custom_id == "start_game_btn" for item in self.children)
            if not has_start_button:
                start_button = discord.ui.Button(
                    label="分身を作成して開始！", 
                    style=discord.ButtonStyle.danger, 
                    custom_id="start_game_btn"
                )
                start_button.callback = self.start_game
                self.add_item(start_button)

        if len(self.players) == self.max_players:
            button.disabled = True
            button.label = "募集終了"

        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(f"参加完了！ {channel.mention} へどうぞ。", ephemeral=True)

    async def start_game(self, interaction: discord.Interaction):
        # 実行者がオーナーかチェック
        if interaction.user.id != self.owner.id:
            await interaction.response.send_message("この操作は募集を開始したユーザーのみ可能です。", ephemeral=True)
            return

        await interaction.response.send_message("ゲームを開始します。分身を生成中...", ephemeral=True)

        final_target = self.target_user or random.choice(self.players)
        numbers = list(range(1, len(self.players) + 1))
        random.shuffle(numbers)

        assignments = {}
        webhook_data = {}

        for i, player in enumerate(self.players):
            circle_num = get_circle_num(numbers[i])
            fake_name = f"{final_target.display_name} {circle_num}"
            is_real = (player.id == final_target.id)

            assignments[player] = {
                "display_name": fake_name,
                "avatar_url": final_target.display_avatar.url,
                "is_real": is_real
            }

            channel = self.channels[player.id]
            webhook = await channel.create_webhook(name=f"Anon-WG-{player.id}")
            webhook_data[channel.id] = webhook.url

            role_msg = "🌟 あなたは **【本物】** です！" if is_real else "👥 あなたは **【分身】** です。"
            start_embed = discord.Embed(
                title="🎭 ゲーム開始：匿名分身人狼",
                description=f"ターゲット: **{final_target.display_name}**\nあなたの名前: **{fake_name}**\n\n{role_msg}",
                color=discord.Color.purple()
            )
            start_embed.set_thumbnail(url=final_target.display_avatar.url)
            await channel.send(embed=start_embed)

        game_logic = self.bot.get_cog("GameLogic")
        if game_logic:
            session_data = {
                "players": self.players,
                "assignments": assignments,
                "channels": self.channels,
                "webhooks": webhook_data,
                "target": final_target
            }
            game_logic.start_game_session(session_data)
        
        await interaction.edit_original_response(content=f"ゲーム開始！ターゲット: {final_target.display_name}")
        await interaction.message.edit(view=None)

class StartCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="start", description="募集を開始します")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.describe(num="最大参加可能人数(3-20)", target="ターゲット")
    async def start(self, interaction: discord.Interaction, num: app_commands.Range[int, 3, 20], target: discord.User = None):
        embed = discord.Embed(title="👤 匿名分身人狼 募集", color=discord.Color.orange())
        embed.description = f"ターゲット: **{target.display_name if target else 'ランダム抽選'}**\n最大定員: **{num}名**\n募集主: {interaction.user.mention}\n※3名以上で開始可能になります。"
        embed.add_field(name=f"参加者 (0/{num})", value="なし", inline=False)
        
        # interaction.userをownerとして渡す
        view = JoinView(self.bot, num, target, interaction.user)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="finish", description="ゲームを終了します")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def finish(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        game_logic = self.bot.get_cog("GameLogic")
        if not game_logic or not game_logic.game_data:
            await interaction.followup.send("実行中のゲームはありません。")
            return
        count = 0
        for channel in game_logic.game_data["channels"].values():
            try: await channel.delete(); count += 1
            except: pass
        game_logic.game_data = None
        await interaction.followup.send(f"終了！ {count}個のチャンネルを削除しました。")

async def setup(bot):
    await bot.add_cog(StartCommand(bot))