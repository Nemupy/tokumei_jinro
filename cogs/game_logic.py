import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import os

GUILD_ID = int(os.getenv("GUILD_ID"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))

class VoteView(discord.ui.View):
    def __init__(self, voter, assignments, game_logic):
        super().__init__(timeout=None)
        self.voter = voter
        self.game_logic = game_logic
        
        # 名前（①②③含む）で昇順にソート
        sorted_assignments = sorted(
            assignments.items(), 
            key=lambda item: item[1]["display_name"]
        )
        
        options = [
            discord.SelectOption(label=data["display_name"], value=str(player.id)) 
            for player, data in sorted_assignments
        ]
        
        self.add_item(VoteSelect(options))

class VoteSelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(placeholder="本物は誰だ？", options=options)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if view.voter.id in view.game_logic.votes:
            await interaction.response.send_message("既に投票済みです。", ephemeral=True)
            return

        # 投票の記録
        view.game_logic.votes[view.voter.id] = int(self.values[0])
        
        # 投票進度の表示
        current_votes = len(view.game_logic.votes)
        total_players = len(view.game_logic.game_data["players"])
        
        await interaction.response.send_message(f"投票完了。 (現在の進捗: {current_votes}/{total_players})", ephemeral=True)
        
        # 全員完了時に結果発表
        if current_votes == total_players:
            await view.game_logic.announce_results(interaction.guild)

class GameLogic(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.game_data = None
        self.votes = {}
        self.is_announcing = False 

    def start_game_session(self, data):
        self.game_data = data
        self.votes = {}
        self.is_announcing = False

    @app_commands.command(name="vote_start", description="投票を開始します")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def vote_start(self, interaction: discord.Interaction):
        if not self.game_data:
            await interaction.response.send_message("ゲームが開始されていません。", ephemeral=True)
            return
        await interaction.response.send_message("各チャンネルに投票メニューを送信しました。", ephemeral=True)
        for p_id, channel in self.game_data["channels"].items():
            view = VoteView(self.bot.get_user(p_id), self.game_data["assignments"], self)
            await channel.send("🔍 **投票フェーズ**：紛れ込んでいる「本物」を選んでください。", view=view)

    async def announce_results(self, guild):
        if self.is_announcing:
            return
        self.is_announcing = True

        embed = discord.Embed(title="📊 結果発表：本物は誰だ？", color=discord.Color.gold())
        
        # 本物の情報を取得
        real_player = next((p for p, d in self.game_data["assignments"].items() if d["is_real"]), None)
        real_fake_name = self.game_data["assignments"][real_player]["display_name"] if real_player else "不明"

        # 投票の内訳と、個人の割り当て名の表示
        res_list = []
        for p in self.game_data["players"]:
            # 投票した相手の情報
            v_id = self.votes.get(p.id)
            v_user = self.bot.get_user(v_id) if v_id else None
            v_name = self.game_data["assignments"][v_user]["display_name"] if v_user else "未投票"
            
            # 判定マーク
            ok = "✅" if v_id == (real_player.id if real_player else None) else "❌"
            
            # その人自身の割り当て名（分身名）を取得
            own_fake_name = self.game_data["assignments"][p]["display_name"]
            
            # フォーマット: 本名 [分身名] ➔ 投票先 [分身名]
            res_list.append(f"**{p.display_name}** [{own_fake_name}] ➔ {v_name} {ok}")
        
        res_text = "\n".join(res_list)
        embed.description = f"{res_text}\n\n✨ **本物の正体は... {real_player.mention} [{real_fake_name}] でした！**"
        
        log_ch = self.bot.get_channel(LOG_CHANNEL_ID)
        target_list = list(self.game_data["channels"].values())
        if log_ch:
            target_list.append(log_ch)

        for ch in target_list:
            await ch.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not self.game_data or self.is_announcing:
            return
        if message.author.id == self.bot.user.id or message.webhook_id:
            return
        
        sender = message.author
        if sender.id not in self.game_data["channels"]:
            return
        if message.channel.id != self.game_data["channels"][sender.id].id:
            return

        fake = self.game_data["assignments"].get(sender)
        if fake:
            await self.relay_message(message, fake)

    async def relay_message(self, msg, fake):
        targets = list(self.game_data["channels"].values())
        log_ch = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_ch:
            targets.append(log_ch)

        allowed_mentions = discord.AllowedMentions.none()

        async with aiohttp.ClientSession() as session:
            for target in targets:
                if target.id == msg.channel.id:
                    continue
                
                url = self.game_data["webhooks"].get(target.id)
                if target.id == LOG_CHANNEL_ID and not url:
                    webhook = await target.create_webhook(name="Spectator")
                    url = webhook.url
                    self.game_data["webhooks"][LOG_CHANNEL_ID] = url
                
                if url:
                    files = [await att.to_file() for att in msg.attachments]
                    webhook = discord.Webhook.from_url(url, session=session)
                    await webhook.send(
                        content=msg.content,
                        username=fake["display_name"],
                        avatar_url=fake["avatar_url"],
                        files=files,
                        allowed_mentions=allowed_mentions
                    )

async def setup(bot):
    await bot.add_cog(GameLogic(bot))
