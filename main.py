import discord
import os
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True
intents.members=True    # 멤버 닉네임 읽기
bot = commands.Bot(command_prefix='!', intents=intents)

# 참가자 명단 저장 변수
participants=[]
# 티어별 기준 점수
TIER_BASE_SCORE = {
    'C': 10000, 'GM': 20000, 'M': 30000,
    'D': 40000, 'E': 50000, 'P': 60000,
    'G': 70000, 'S': 80000, 'B': 90000, 'I': 100000
}
# TIER_ORDER = ['C','GM','M','D','E','P','G','S','B','I']

@bot.event
async def on_message(message):
    global participants
    if message.author.bot:
        return

    # 참가 처리
    if message.content in ['손','ㅅ','t']:
        user_nickname = message.author.display_name
        # 닉네임 형식 확인
        if '/' not in user_nickname:
            await message.channel.send(f"{message.author.mention}님 닉네임 형식을 바꿔주세요!")
            return
        # 중복 참가 확인
        if any(p['id']== message.author.id for p in participants):
            return
        # 정보 추출
        try:
            parts = user_nickname.split('/')
            tier_info = parts[1].strip()

            total_score = 999999
            current_tier_name = "언랭"

            for tier_name, base_score in TIER_BASE_SCORE.items():
                if tier_name in tier_info:
                    current_tier_name = tier_name
                    num_part = "".join(filter(str.isdigit, tier_info))
                    num_val = int(num_part) if num_part else 0

                    if tier_name in ['C','GM', 'M']:    # 고티어
                        total_score = base_score -num_val
                    else:   # 저티어
                        total_score = base_score +num_val
                    break
            participants.append({
                'id': message.author.id,
                'full_name': user_nickname,
                'tier_name': current_tier_name,
                'score': total_score
            })

            await message.channel.send(f"✅ {user_nickname.split('/')[0]}님 참가! ({len(participants)}/10)")

        except Exception as e:
            print(f"Error: {e}")
            await message.channel.send("닉네임 형식 오류!")
            return

        # 10명이 모이면 시작
        if len(participants) == 2:
            # 티어 순 정렬
            participants.sort(key=lambda x: x['score'])

            embed = discord.Embed(title="⭐ 참여자 티어 정보", color=0x3498db)
            display_text = ""
            last_tier = None

            for p in participants:
                if last_tier is not None and last_tier != p['tier_name']:
                    display_text += "\n"
                display_text += f"{p['full_name']}\n"
                last_tier = p['tier_name']


            embed.description = display_text
            await message.channel.send(embed=embed)
            embed.set_footer(text="'손', 'ㅅ', 't' 참가 메시지를 인식합니다.")
            participants=[]


    await bot.process_commands(message)
# 초기화
@bot.command()
async def 초기화(ctx):
    global participants
    participants = []
    await ctx.send("모집 명단이 초기화되었습니다.")

token=os.getenv('DISCORD_TOKEN')
bot.run(token)