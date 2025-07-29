import json
import requests
from discord.ext import commands, tasks
import discord
from discord import app_commands
from io import BytesIO
import re
from typing import Optional
import os

TOKEN = 'token'

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

guild_settings = {}
guild_dictionaries = {}

DEFAULT_SETTINGS = {
    "speed": 1.0,
    "pitch": 0.0,
    "intonation": 1.0,
}

SETTINGS_FILE = "settings.json"
DICTIONARY_FILE = "dictionary.json"

def load_settings():
    global guild_settings
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r') as f:
            guild_settings = json.load(f)
    else:
        guild_settings = {}

def save_settings():
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(guild_settings, f, indent=4)

def load_dictionary():
    global guild_dictionaries
    if os.path.exists(DICTIONARY_FILE):
        with open(DICTIONARY_FILE, 'r') as f:
            guild_dictionaries = json.load(f)
    else:
        guild_dictionaries = {}

def save_dictionary():
    with open(DICTIONARY_FILE, 'w') as f:
        json.dump(guild_dictionaries, f, indent=4)

load_settings()
load_dictionary()

def talk(text: str, speed: float, pitch: float, intonation: float) -> Optional[BytesIO]:
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
            timeout=10
        )
        response.raise_for_status()
        return BytesIO(response.content)
    except requests.exceptions.RequestException as e:
        print(f"音声合成APIへの接続に失敗しました: {e}")
        return None

def process_message(text: str, guild_id: int) -> str:
    guild_id_str = str(guild_id)
    if guild_id_str in guild_dictionaries:
        for word, reading in guild_dictionaries[guild_id_str].items():
            text = text.replace(word, reading)
            
    url_pattern = r'https?://\S+|www\.\S+'
    if re.fullmatch(url_pattern, text.strip()):
        return 'リンク省略'
    return re.sub(url_pattern, 'リンク省略', text)

class MyClient(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def on_ready(self):
        await self.tree.sync()
        auto_leave.start()
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
            
            processed_text = process_message(message.content, message.guild.id)
            if not processed_text.strip():
                return
            
            guild_id_str = str(message.guild.id)
            settings = guild_settings.get(guild_id_str, DEFAULT_SETTINGS)

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
            else:
                await message.channel.send(f"⚠️ 音声の生成に失敗しました。\nAPIサーバーが起動しているか確認してください。")

client = MyClient(intents=intents)

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
    guild_id_str = str(interaction.guild.id)

    if guild_id_str not in guild_settings:
        guild_settings[guild_id_str] = DEFAULT_SETTINGS.copy()

    if speed is not None:
        guild_settings[guild_id_str]["speed"] = speed
    if pitch is not None:
        guild_settings[guild_id_str]["pitch"] = pitch
    if intonation is not None:
        guild_settings[guild_id_str]["intonation"] = intonation
    
    save_settings()
    
    current = guild_settings[guild_id_str]
    embed = discord.Embed(title="⚙️ 読み上げ設定", description="現在の音声設定です。", color=discord.Color.blue())
    embed.add_field(name="速さ", value=f"`{current['speed']}`", inline=True)
    embed.add_field(name="高さ", value=f"`{current['pitch']}`", inline=True)
    embed.add_field(name="抑揚", value=f"`{current['intonation']}`", inline=True)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

jisyo_group = app_commands.Group(name="jisyo", description="単語と読み方を登録・管理します。")

@jisyo_group.command(name="add", description="辞書に新しい単語と読み方を登録します。")
@app_commands.rename(word="単語", reading="読み方")
async def jisyo_add(interaction: discord.Interaction, word: str, reading: str):
    guild_id_str = str(interaction.guild.id)
    if guild_id_str not in guild_dictionaries:
        guild_dictionaries[guild_id_str] = {}
        
    guild_dictionaries[guild_id_str][word] = reading
    save_dictionary()
    await interaction.response.send_message(f"✅ 単語「`{word}`」を「`{reading}`」として登録しました。", ephemeral=True)

@jisyo_group.command(name="remove", description="辞書から単語を削除します。")
@app_commands.rename(word="単語")
async def jisyo_remove(interaction: discord.Interaction, word: str):
    guild_id_str = str(interaction.guild.id)
    if guild_id_str in guild_dictionaries and word in guild_dictionaries[guild_id_str]:
        del guild_dictionaries[guild_id_str][word]
        save_dictionary()
        await interaction.response.send_message(f"🗑️ 単語「`{word}`」を辞書から削除しました。", ephemeral=True)
    else:
        await interaction.response.send_message(f"🤔 単語「`{word}`」は辞書に登録されていません。", ephemeral=True)

@jisyo_group.command(name="list", description="登録されている単語のリストを表示します。")
async def jisyo_list(interaction: discord.Interaction):
    guild_id_str = str(interaction.guild.id)
    if guild_id_str in guild_dictionaries and guild_dictionaries[guild_id_str]:
        embed = discord.Embed(title="📖 辞書登録リスト", color=discord.Color.green())
        description = ""
        for word, reading in guild_dictionaries[guild_id_str].items():
            description += f"**{word}** → **{reading}**\n"
        embed.description = description
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message("辞書にはまだ何も登録されていません。", ephemeral=True)

client.tree.add_command(jisyo_group)

@tasks.loop(seconds=10)
async def auto_leave():
    for guild in client.guilds:
        voice_client = guild.voice_client
        if voice_client and voice_client.is_connected():
            members = voice_client.channel.members
            non_bot_members = [m for m in members if not m.bot]
            if not non_bot_members:
                await voice_client.disconnect()
                print(f"{guild.name}のボイスチャンネルから自動退出しました。")

if __name__ == "__main__":
    client.run(TOKEN)
