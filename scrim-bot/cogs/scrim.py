import logging
import unicodedata

import discord
from discord import app_commands
from discord.ext import commands

import db
from nickname import ParsedNickname, parse_nickname

log = logging.getLogger("scrim-bot.scrim")


NICK_FORMAT_HELP = (
    "❌ 닉네임 형식이 맞지 않아요.\n\n"
    "**형식**: `롤닉네임#태그/티어/라인`\n\n"
    "**예시** (영문/한글 다 입력 가능, 표시는 영문 통일):\n"
    "• `완댕이#명명펀치/M350/TOP.MID.SUP`\n"
    "• `정도#kr1/E2/MID,AD`\n"
    "• `석이#No1/G3/SUP`\n\n"
    "**티어**: C / GM / M{LP} / D{1-4} / E{1-4} / P{1-4} / G{1-4} / S{1-4} / B{1-4} / I{1-4}\n"
    "**라인**: TOP / JG / MID / AD / SUP\n\n"
    "**변경 방법**: 서버 멤버 목록에서 본인 우클릭 → "
    "**별명 변경** → 위 형식대로 저장."
)

COLOR_OPEN = 0x3498DB
COLOR_SUMMARY = 0xFFD700


async def _resolve_member(guild: discord.Guild, user_id: int) -> discord.Member | None:
    member = guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(user_id)
    except (discord.NotFound, discord.HTTPException):
        return None


def _format_line(idx: int, uid: int, member: discord.Member | None, parsed: ParsedNickname | None) -> str:
    if parsed and parsed.is_valid:
        return f"`{idx:>2}.` **{parsed.name}** / {parsed.tier_display} / {parsed.positions_display}"
    if member is not None:
        return f"`{idx:>2}.` {member.mention} ⚠️ 닉네임 형식 확인 필요"
    return f"`{idx:>2}.` <@{uid}> ⚠️ 멤버 정보 없음"


def _display_width(s: str) -> int:
    w = 0
    for c in s:
        w += 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
    return w


def _ljust_visual(s: str, n: int) -> str:
    return s + " " * max(0, n - _display_width(s))


def _format_grouped_aligned(items) -> str:
    """티어 그룹별로 빈 줄을 끼우고, 코드블록 안에서 컬럼 정렬."""
    if not items:
        return "없음"

    rows: list[tuple[str, str, str, str]] = []
    for uid, member, parsed in items:
        if parsed and parsed.is_valid:
            rows.append((parsed.name, parsed.tier_display, parsed.positions_display, parsed.tier_name))
        elif member is not None:
            rows.append((member.display_name, "?", "닉 형식 확인 필요", "_invalid"))
        else:
            rows.append((f"id:{uid}", "?", "멤버 정보 없음", "_invalid"))

    name_w = max(_display_width(r[0]) for r in rows)
    tier_w = max(_display_width(r[1]) for r in rows)
    SEP = "    "  # 컬럼 사이 4칸

    lines: list[str] = []
    last: str | None = None
    for name, tier_text, pos, key in rows:
        if last is not None and last != key:
            lines.append("")
        last = key
        lines.append(
            f"{_ljust_visual(name, name_w)}{SEP}{_ljust_visual(tier_text, tier_w)}{SEP}{pos}"
        )

    return "```\n" + "\n".join(lines) + "\n```"


async def _resolve_participants(bot: commands.Bot, scrim_row):
    """Returns (main_list, wait_list) of (uid, member, parsed) tuples."""
    guild = bot.get_guild(scrim_row["guild_id"])
    raw = db.get_participants(scrim_row["scrim_id"])
    main_list: list[tuple[int, discord.Member | None, ParsedNickname | None]] = []
    wait_list: list[tuple[int, discord.Member | None, ParsedNickname | None]] = []
    for uid, is_wl in raw:
        if guild is not None:
            member = await _resolve_member(guild, uid)
            parsed = parse_nickname(member.display_name) if member else None
        else:
            member, parsed = None, None
        (wait_list if is_wl else main_list).append((uid, member, parsed))
    return main_list, wait_list


def _tier_sort_key(item):
    _, _, parsed = item
    if parsed and parsed.is_valid:
        return (0, -parsed.tier_order, -parsed.tier_score)
    return (1, 0, 0)


async def build_embed(bot: commands.Bot, scrim_row) -> discord.Embed:
    capacity = scrim_row["capacity"]
    main_list, wait_list = await _resolve_participants(bot, scrim_row)

    n_main = len(main_list)
    remaining = max(0, capacity - n_main)

    embed = discord.Embed(
        title="🎮 내전 모집 · 진행중",
        description=f"현재 **{n_main}/{capacity}**명, 남은 자리 **{remaining}**",
        color=COLOR_OPEN,
    )

    if main_list:
        lines = [_format_line(i, uid, m, p) for i, (uid, m, p) in enumerate(main_list, 1)]
        embed.add_field(name="✅ 참가자 (참가 순)", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="✅ 참가자 (참가 순)", value="없음", inline=False)

    wait_label = f"🕐 대기자 ({len(wait_list)}명)" if wait_list else "🕐 대기자"
    if wait_list:
        lines = [_format_line(i, uid, m, p) for i, (uid, m, p) in enumerate(wait_list, 1)]
        embed.add_field(name=wait_label, value="\n".join(lines), inline=False)
    else:
        embed.add_field(name=wait_label, value="없음", inline=False)

    embed.set_footer(text="닉네임 형식: 롤닉네임#태그/티어/라인  (예: 완댕이#명명펀치/M350/MID.TOP)")
    return embed


async def build_summary_embed(bot: commands.Bot, scrim_row) -> discord.Embed:
    """참가자를 티어 그룹별로 정리한 임베드."""
    main_list, _ = await _resolve_participants(bot, scrim_row)
    main_list.sort(key=_tier_sort_key)

    embed = discord.Embed(title="⭐ 참여자 티어 정보", color=COLOR_SUMMARY)
    embed.description = _format_grouped_aligned(main_list) if main_list else "참여자 없음"
    return embed


class ScrimView(discord.ui.View):
    def __init__(self, scrim_id: int, is_full: bool = False):
        super().__init__(timeout=None)
        self.scrim_id = scrim_id

        self.join_btn = discord.ui.Button(
            label="참가하기",
            style=discord.ButtonStyle.success,
            custom_id=f"scrim:{scrim_id}:join",
            emoji="🟢",
        )
        self.join_btn.callback = self._on_join
        self.add_item(self.join_btn)

        self.cancel_btn = discord.ui.Button(
            label="취소하기",
            style=discord.ButtonStyle.danger,
            custom_id=f"scrim:{scrim_id}:cancel",
            emoji="🔴",
        )
        self.cancel_btn.callback = self._on_cancel
        self.add_item(self.cancel_btn)

        self.summary_btn = discord.ui.Button(
            label="정리",
            style=discord.ButtonStyle.primary,
            custom_id=f"scrim:{scrim_id}:summary",
            emoji="📋",
            disabled=not is_full,
        )
        self.summary_btn.callback = self._on_summary
        self.add_item(self.summary_btn)

    def _update_button_state(self, main_count: int, capacity: int) -> None:
        self.summary_btn.disabled = main_count < capacity

    async def _refresh(self, interaction: discord.Interaction) -> None:
        scrim = db.get_scrim(self.scrim_id)
        participants = db.get_participants(self.scrim_id)
        main_count = sum(1 for _, wl in participants if not wl)
        self._update_button_state(main_count, scrim["capacity"])
        embed = await build_embed(interaction.client, scrim)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_join(self, interaction: discord.Interaction):
        scrim = db.get_scrim(self.scrim_id)
        if scrim is None:
            await interaction.response.send_message("모집 정보를 찾을 수 없습니다.", ephemeral=True)
            return

        parsed = parse_nickname(interaction.user.display_name)
        if not parsed.is_valid:
            await interaction.response.send_message(NICK_FORMAT_HELP, ephemeral=True)
            return

        participants = db.get_participants(self.scrim_id)
        if any(uid == interaction.user.id for uid, _ in participants):
            await interaction.response.send_message("이미 참가 중입니다.", ephemeral=True)
            return

        main_count_before = sum(1 for _, wl in participants if not wl)
        as_waitlist = main_count_before >= scrim["capacity"]

        if not db.add_participant(self.scrim_id, interaction.user.id, as_waitlist):
            await interaction.response.send_message("이미 참가 중입니다.", ephemeral=True)
            return

        await self._refresh(interaction)

        if as_waitlist:
            await interaction.followup.send(
                "🕐 정원이 다 차서 **대기자**로 등록되었어요. "
                "정원에서 한 자리 비면 자동으로 참가자가 됩니다.",
                ephemeral=True,
            )

    async def _on_cancel(self, interaction: discord.Interaction):
        scrim = db.get_scrim(self.scrim_id)
        if scrim is None:
            await interaction.response.send_message("모집 정보를 찾을 수 없습니다.", ephemeral=True)
            return

        participants = db.get_participants(self.scrim_id)
        target_wl = next((wl for uid, wl in participants if uid == interaction.user.id), None)
        if target_wl is None:
            await interaction.response.send_message("참가 중이 아닙니다.", ephemeral=True)
            return

        was_main = (target_wl == 0)
        db.remove_participant(self.scrim_id, interaction.user.id)
        promoted_uid = db.promote_oldest_waitlist(self.scrim_id) if was_main else None

        await self._refresh(interaction)
        if promoted_uid is not None:
            await interaction.followup.send(
                f"<@{promoted_uid}>님이 대기자에서 참가자로 자동 승격되었어요! 🎉",
                ephemeral=False,
            )

    async def _on_summary(self, interaction: discord.Interaction):
        scrim = db.get_scrim(self.scrim_id)
        if scrim is None:
            await interaction.response.send_message("모집 정보를 찾을 수 없습니다.", ephemeral=True)
            return

        participants = db.get_participants(self.scrim_id)
        main_count = sum(1 for _, wl in participants if not wl)
        if main_count < scrim["capacity"]:
            await interaction.response.send_message(
                f"아직 정원이 안 찼어요 ({main_count}/{scrim['capacity']})", ephemeral=True
            )
            return

        await interaction.response.defer()
        summary = await build_summary_embed(interaction.client, scrim)
        await interaction.channel.send(embed=summary)


class ScrimCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        rows = db.get_persistent_scrims()
        for row in rows:
            scrim = db.get_scrim(row["scrim_id"])
            participants = db.get_participants(row["scrim_id"])
            main_count = sum(1 for _, wl in participants if not wl)
            is_full = scrim is not None and main_count >= scrim["capacity"]
            self.bot.add_view(
                ScrimView(row["scrim_id"], is_full=is_full),
                message_id=row["message_id"],
            )
        log.info("Restored %d scrim view(s)", len(rows))

    @app_commands.command(name="내전모집", description="LoL 내전 참가자 모집 시작")
    @app_commands.describe(정원="모집 정원 (기본 10명)")
    @app_commands.choices(정원=[
        app_commands.Choice(name="2명 (테스트)", value=2),
        app_commands.Choice(name="10명", value=10),
        app_commands.Choice(name="20명", value=20),
    ])
    async def naejeon(
        self,
        interaction: discord.Interaction,
        정원: app_commands.Choice[int] | None = None,
    ):
        if interaction.guild is None:
            await interaction.response.send_message("서버에서만 사용할 수 있습니다.", ephemeral=True)
            return

        capacity = 정원.value if 정원 is not None else 10

        scrim_id = db.create_scrim(
            guild_id=interaction.guild.id,
            channel_id=interaction.channel.id,
            creator_id=interaction.user.id,
            capacity=capacity,
        )
        scrim = db.get_scrim(scrim_id)
        embed = await build_embed(self.bot, scrim)
        view = ScrimView(scrim_id)

        await interaction.response.send_message(embed=embed, view=view)
        msg = await interaction.original_response()
        db.set_message_id(scrim_id, msg.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(ScrimCog(bot))
