import json
import requests
from discord.ext import commands
import discord
from discord import app_commands # スラッシュコマンドのために必要
from io import BytesIO
import re  # URLの検出に使用

# --------------------------------------------------------------------------------
# グローバル変数と設定
# --------------------------------------------------------------------------------

# Discord Botのトークンをここに設定してください
TOKEN = 'tokenhere'

# インテントの設定 (Botが必要とする権限)
intents = discord.Intents.default()
intents.message_content = True  # メッセージ内容の読み取り
intents.voice_states = True     # ボイスチャンネルの状態変化の検知
intents.members = True          # サーバーのメンバー情報の取得

# --------------------------------------------------------------------------------
# 音声合成 & メッセージ処理関数
# --------------------------------------------------------------------------------

def talk(text: str) -> BytesIO:
    """
    指定されたテキストを音声合成APIに送信し、音声データを生成します。
    この関数はローカルで実行されている音声合成エンジン（例：VOICEVOX）を想定しています。
    """
    # メッセージから絵文字やコードブロックなどの特殊なマークダウンを除去
    text = re.sub(r'<.*?>', '', text)
    
    # 音声合成APIへのリクエストボディ
    query = {
        "speakerUuid": "697e0e2c-fda8-11ef-b33b-0242ac1c000c",
        "styleId": 379136521,
        "text": text,
        "speedScale": 1.0,
        "volumeScale": 1.0,
        "prosodyDetail": [],
        "pitchScale": 0.0,
        "intonationScale": 1.0,
        "prePhonemeLength": 0.1,
        "postPhonemeLength": 0.5,
        "outputSamplingRate": 24000,
    }

    try:
        # 音声合成APIにPOSTリクエストを送信
        response = requests.post(
            "http://127.0.0.1:2080/v1/synthesis",
            headers={"Content-Type": "application/json"},
            data=json.dumps(query),
            timeout=10 # タイムアウトを10秒に設定
        )
        # エラーがあれば例外を発生させる
        response.raise_for_status()
        # 音声データをBytesIOオブジェクトとして返す
        return BytesIO(response.content)
    except requests.exceptions.RequestException as e:
        print(f"音声合成APIへの接続に失敗しました: {e}")
        return None

def process_message(text: str) -> str:
    """
    メッセージ内のURLを検出し、「リンク省略」という文字列に置き換えます。
    """
    # URLを検出するための正規表現パターン
    url_pattern = r'https?://\S+|www\.\S+'
    
    # メッセージ全体がURLであるかチェック
    if re.fullmatch(url_pattern, text.strip()):
        return 'リンク省略'
    
    # メッセージ内のURL部分のみを置換
    return re.sub(url_pattern, 'リンク省略', text)

# --------------------------------------------------------------------------------
# Discord Botのクライアント定義
# --------------------------------------------------------------------------------

class MyClient(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        # スラッシュコマンドを管理するためのツリーを作成
        self.tree = app_commands.CommandTree(self)

    async def on_ready(self):
        """
        Botが起動し、Discordとの接続が完了したときに呼び出されるイベント
        """
        # コマンドツリーをDiscordサーバーに同期
        await self.tree.sync()
        print(f'{self.user} としてログインしました (ID: {self.user.id})')
        print('スラッシュコマンドが同期され、Botの準備が完了しました。')
        print('------')

    async def on_message(self, message: discord.Message):
        """
        サーバー内でメッセージが送信されたときに呼び出されるイベント
        """
        # メッセージの送信者がBot自身の場合は何もしない
        if message.author.bot:
            return

        # Botがボイスチャンネルに接続しているか確認
        voice_client = message.guild.voice_client
        if voice_client and voice_client.is_connected():
            # 読み上げるテキストがない場合は処理を中断
            if not message.content.strip():
                return

            # メッセージ内のURLを処理
            processed_text = process_message(message.content)

            # 処理後のテキストが空になった場合は処理を中断
            if not processed_text.strip():
                return
            
            # 音声合成が完了するまで待機
            while voice_client.is_playing():
                await discord.utils.sleep_until(lambda: not voice_client.is_playing())

            # 音声データを生成
            audio_data = talk(processed_text)
            
            if audio_data:
                # 音声ファイルを再生
                # BytesIOを直接ソースとして渡すことで、ファイルへの書き込みが不要になる
                source = discord.FFmpegPCMAudio(audio_data, pipe=True)
                voice_client.play(source, after=lambda e: print(f"再生完了" if not e else f"再生エラー: {e}"))

# Botクライアントのインスタンスを作成
client = MyClient(intents=intents)

# --------------------------------------------------------------------------------
# スラッシュコマンドの定義
# --------------------------------------------------------------------------------

@client.tree.command(name="join", description="Botが現在あなたが参加しているボイスチャンネルに接続します。")
async def join(interaction: discord.Interaction):
    """
    /join コマンド: Botをボイスチャンネルに接続させる
    """
    # コマンド実行者がボイスチャンネルに参加しているか確認
    if interaction.user.voice is None:
        await interaction.response.send_message("先にボイスチャンネルに参加してください。", ephemeral=True)
        return

    voice_channel = interaction.user.voice.channel
    
    # すでに他のボイスチャンネルに接続している場合は、切断してから接続する
    if interaction.guild.voice_client is not None:
        await interaction.guild.voice_client.disconnect()

    # ボイスチャンネルに接続
    try:
        await voice_channel.connect()
        await interaction.response.send_message(f"`{voice_channel.name}` に接続しました！", ephemeral=False)
    except Exception as e:
        await interaction.response.send_message(f"接続に失敗しました: {e}", ephemeral=True)

@client.tree.command(name="leave", description="Botがボイスチャンネルから切断します。")
async def leave(interaction: discord.Interaction):
    """
    /leave コマンド: Botをボイスチャンネルから切断させる
    """
    # Botがボイスチャンネルに接続しているか確認
    if interaction.guild.voice_client is None:
        await interaction.response.send_message("Botはどのボイスチャンネルにも接続していません。", ephemeral=True)
        return

    # ボイスチャンネルから切断
    await interaction.guild.voice_client.disconnect()
    await interaction.response.send_message("ボイスチャンネルから切断しました。", ephemeral=False)

# --------------------------------------------------------------------------------
# Botの実行
# --------------------------------------------------------------------------------
if __name__ == "__main__":
    client.run(TOKEN)
