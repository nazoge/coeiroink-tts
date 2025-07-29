import json
import requests
from discord.ext import commands
import discord
from discord import app_commands
from io import BytesIO
import re
from typing import Optional

# --------------------------------------------------------------------------------
# グローバル変数と設定
# --------------------------------------------------------------------------------

TOKEN = 'tokenhere'

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

guild_settings = {}

DEFAULT_SETTINGS = {
    "speed": 1.0,
    "pitch": 0.0,
    "intonation": 1.0,
}

# --------------------------------------------------------------------------------
# 音声合成 & メッセージ処理関数
# --------------------------------------------------------------------------------

def talk(text: str, speed: float, pitch: float, intonation: float) -> Optional[BytesIO]:
    """
    指定されたパラメータでテキストを音声合成し、音声データを生成します。
    """
    text = re.sub(r'<.*?>', '', text)
    
    query = {
        "speakerUuid": "697e0e2c-fda8-11ef-b33b-0242ac1c000c",
        "styleId": 379136521,
        "text": text,
        "speedScale": speed,
        "pitchScale": pitch,
        "intonationScale": intonation,
        "volumeScale": 1.0,
        "prosodyDetail": [],
        "prePhonemeLength": 0.1,
        "postPhonemeLength": 0.5,
        "outputSamplingRate": 24000,
    }

    try:
        response = requests.post(
            "http://127.0.0.1:2080/v1/synthesis",
            headers={"Content-Type": "application/json"},
            data=json.dumps(query),
            timeout=30
        )
        response.raise_for_status()
        return BytesIO(response.content)
    except requests.exceptions.RequestException as e:
        print(f"音声合成APIへの接続に失敗しました: {e}")
        return None

def process_message(text: str) -> str:
    """
    メッセージ内のURLを「リンク省略」に置き換えます。
    """
    url_pattern = r'https?://\S+|www\.\S+'
    if re.fullmatch(url_pattern, text.strip()):
        return 'リンク省略'
    return re.sub(url_pattern, 'リンク省略', text)

# --------------------------------------------------------------------------------
# Discord Botのクライアント定義
# --------------------------------------------------------------------------------

class MyClient(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def on_ready(self):
        await self.tree.sync()
        print(f'{self.user} としてログインしました (ID: {self.user.id})')
        print('スラッシュコマンドが同期され、Botの準備が完了しました。')
        print('------')

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        voice_client = message.guild.voice_client
        if voice_client and voice_client.is_connected():
            if not message.content.strip():
                return

            processed_text = process_message(message.content)
            if not processed_text.strip():
                return
            
            settings = guild_settings.get(message.guild.id, DEFAULT_SETTINGS)

            while voice_client.is_playing():
                await discord.utils.sleep_until(lambda: not voice_client.is_playing())

            audio_data = talk(
                processed_text,
                speed=settings["speed"],
                pitch=settings["pitch"],
                intonation=settings["intonation"]
            )
            
            if audio_data:
                source = discord.FFmpegPCMAudio(audio_data, pipe=True)
                voice_client.play(source, after=lambda e: print(f"再生完了" if not e else f"再生エラー: {e}"))

client = MyClient(intents=intents)

# --------------------------------------------------------------------------------
# スラッシュコマンドの定義
# --------------------------------------------------------------------------------

@client.tree.command(name="join", description="Botがあなたが参加しているボイスチャンネルに接続します。")
async def join(interaction: discord.Interaction):
    if interaction.user.voice is None:
        await interaction.response.send_message("先にボイスチャンネルに参加してください。", ephemeral=True)
        return

    if interaction.guild.voice_client is not None:
        await interaction.response.send_message(
            f"Botは既に `{interaction.guild.voice_client.channel.name}` で使用されています。先に `/leave` で退出させてください。",
            ephemeral=True
        )
        return

    voice_channel = interaction.user.voice.channel
    try:
        await voice_channel.connect()
        await interaction.response.send_message(f"`{voice_channel.name}` に接続しました！", ephemeral=False)
    except Exception as e:
        await interaction.response.send_message(f"接続に失敗しました: {e}", ephemeral=True)

@client.tree.command(name="leave", description="Botがボイスチャンネルから切断します。")
async def leave(interaction: discord.Interaction):
    if interaction.guild.voice_client is None:
        await interaction.response.send_message("Botはどのボイスチャンネルにも接続していません。", ephemeral=True)
        return

    await interaction.guild.voice_client.disconnect()
    await interaction.response.send_message("ボイスチャンネルから切断しました。", ephemeral=False)

@client.tree.command(name="setting", description="読み上げ音声の速さ、高さ、抑揚を設定します。")
@app_commands.rename(
    speed="速さ",
    pitch="高さ",
    intonation="抑揚"
)
@app_commands.describe(
    speed="話す速さ (0.5から2.0の範囲)",
    pitch="声の高さ (-0.5から0.5の範囲)",
    intonation="抑揚の強さ (0.0から2.0の範囲)"
)
async def setting(
    interaction: discord.Interaction,
    speed: Optional[app_commands.Range[float, 0.5, 2.0]] = None,
    pitch: Optional[app_commands.Range[float, -0.5, 0.5]] = None,
    intonation: Optional[app_commands.Range[float, 0.0, 2.0]] = None
):
    guild_id = interaction.guild.id

    if guild_id not in guild_settings:
        guild_settings[guild_id] = DEFAULT_SETTINGS.copy()

    if speed is not None:
        guild_settings[guild_id]["speed"] = speed
    if pitch is not None:
        guild_settings[guild_id]["pitch"] = pitch
    if intonation is not None:
        guild_settings[guild_id]["intonation"] = intonation
    
    current = guild_settings[guild_id]
    embed = discord.Embed(title="⚙️ 読み上げ設定", description="現在の音声設定です。", color=discord.Color.blue())
    embed.add_field(name="速さ", value=f"`{current['speed']}`", inline=True)
    embed.add_field(name="高さ", value=f"`{current['pitch']}`", inline=True)
    embed.add_field(name="抑揚", value=f"`{current['intonation']}`", inline=True)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --------------------------------------------------------------------------------
# Botの実行
# --------------------------------------------------------------------------------
if __name__ == "__main__":
    client.run(TOKEN)
