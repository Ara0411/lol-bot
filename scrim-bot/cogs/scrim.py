import logging
import unicodedata
from dataclasses import dataclass

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


@dataclass
class Participant:
    is_proxy: bool
    parsed: ParsedNickname | None
    # own
    uid: int | None = None
    member: discord.Member | None = None
    # proxy
    name: str | None = None
    proxy_by_user_id: int | None = None
    proxy_by_name: str | None = None


async def _resolve_member(guild: discord.Guild, user_id: int) -> discord.Member | None:
    member = guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(user_id)
    except (discord.NotFound, discord.HTTPException):
        return None


def _display_width(s: str) -> int:
    w = 0
    for c in s:
        w += 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
    return w


def _ljust_visual(s: str, n: int) -> str:
    return s + " " * max(0, n - _display_width(s))


def _participant_display_name(p: Participant) -> str:
    """이름 컬럼에 표시할 문자열."""
    if p.parsed and p.parsed.is_valid:
        return p.parsed.name
    if p.is_proxy:
        return p.name or "?"
    if p.member is not None:
        return p.member.display_name
    return f"id:{p.uid}"


def _format_line(idx: int, p: Participant) -> str:
    """모집 중(번호 매기는) 표시. 마크다운 활성."""
    if p.parsed and p.parsed.is_valid:
        base = f"`{idx:>2}.` **{p.parsed.name}** / {p.parsed.tier_display} / {p.parsed.positions_display}"
        if p.is_proxy:
            base += f"  *(대리: {p.proxy_by_name or '?'})*"
        return base
    # invalid nickname fallback
    if p.is_proxy:
        return f"`{idx:>2}.` **{p.name}** ⚠️ 닉 형식 오류 *(대리: {p.proxy_by_name or '?'})*"
    if p.member is not None:
        return f"`{idx:>2}.` {p.member.mention} ⚠️ 닉네임 형식 확인 필요"
    return f"`{idx:>2}.` <@{p.uid}> ⚠️ 멤버 정보 없음"


def _format_grouped_aligned(items: list[Participant]) -> str:
    """티어 그룹별로 빈 줄 + 코드블록 안 컬럼 정렬 (마감/정리용)."""
    if not items:
        return "없음"

    rows: list[tuple[str, str, str, str, str]] = []
    # (name, tier_text, pos, tier_name_key, suffix)
    for p in items:
        if p.parsed and p.parsed.is_valid:
            suffix = f"(대리: {p.proxy_by_name or '?'})" if p.is_proxy else ""
            rows.append((p.parsed.name, p.parsed.tier_display, p.parsed.positions_display, p.parsed.tier_name, suffix))
        elif p.is_proxy:
            rows.append((p.name or "?", "?", "닉 형식 오류", "_invalid", f"(대리: {p.proxy_by_name or '?'})"))
        elif p.member is not None:
            rows.append((p.member.display_name, "?", "닉 형식 확인 필요", "_invalid", ""))
        else:
            rows.append((f"id:{p.uid}", "?", "멤버 정보 없음", "_invalid", ""))

    name_w = max(_display_width(r[0]) for r in rows)
    tier_w = max(_display_width(r[1]) for r in rows)
    pos_w = max(_display_width(r[2]) for r in rows)
    SEP = "    "

    lines: list[str] = []
    last: str | None = None
    for name, tier_text, pos, key, suffix in rows:
        if last is not None and last != key:
            lines.append("")
        last = key
        line = f"{_ljust_visual(name, name_w)}{SEP}{_ljust_visual(tier_text, tier_w)}{SEP}{_ljust_visual(pos, pos_w)}"
        if suffix:
            line += f"{SEP}{suffix}"
        lines.append(line)

    return "```\n" + "\n".join(lines) + "\n```"


async def _resolve_participants(bot: commands.Bot, scrim_row):
    """본인 + 대리 참가자 통합. (main_list, wait_list of Participant)."""
    guild = bot.get_guild(scrim_row["guild_id"])
    main_list: list[Participant] = []
    wait_list: list[Participant] = []

    # 본인 참가자
    for uid, is_wl in db.get_participants(scrim_row["scrim_id"]):
        if guild is not None:
            member = await _resolve_member(guild, uid)
            parsed = parse_nickname(member.display_name) if member else None
        else:
            member, parsed = None, None
        p = Participant(is_proxy=False, uid=uid, member=member, parsed=parsed)
        (wait_list if is_wl else main_list).append(p)

    # 대리 참가자
    for row in db.get_proxy_participants(scrim_row["scrim_id"]):
        nick_str = f"{row['name']}/{row['tier_raw']}/{row['positions']}"
        parsed = parse_nickname(nick_str)
        proxy_by_name = "?"
        if guild is not None:
            proxy_by = await _resolve_member(guild, row["proxy_by_user_id"])
            if proxy_by:
                proxy_by_parsed = parse_nickname(proxy_by.display_name)
                proxy_by_name = proxy_by_parsed.name if proxy_by_parsed.is_valid else proxy_by.display_name
        p = Participant(
            is_proxy=True,
            parsed=parsed,
            name=row["name"],
            proxy_by_user_id=row["proxy_by_user_id"],
            proxy_by_name=proxy_by_name,
        )
        (wait_list if row["is_waitlist"] else main_list).append(p)

    return main_list, wait_list


def _tier_sort_key(p: Participant):
    if p.parsed and p.parsed.is_valid:
        return (0, -p.parsed.tier_order, -p.parsed.tier_score)
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
        lines = [_format_line(i, p) for i, p in enumerate(main_list, 1)]
        embed.add_field(name="✅ 참가자 (참가 순)", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="✅ 참가자 (참가 순)", value="없음", inline=False)

    wait_label = f"🕐 대기자 ({len(wait_list)}명)" if wait_list else "🕐 대기자"
    if wait_list:
        lines = [_format_line(i, p) for i, p in enumerate(wait_list, 1)]
        embed.add_field(name=wait_label, value="\n".join(lines), inline=False)
    else:
        embed.add_field(name=wait_label, value="없음", inline=False)

    embed.set_footer(text="닉네임 형식: 롤닉네임#태그/티어/라인  (예: 완댕이#명명펀치/M350/MID.TOP) · /대신참가 로 대리 등록 가능")
    return embed


async def build_summary_embed(bot: commands.Bot, scrim_row) -> discord.Embed:
    main_list, _ = await _resolve_participants(bot, scrim_row)
    main_list.sort(key=_tier_sort_key)

    embed = discord.Embed(title="⭐ 참여자 티어 정보", color=COLOR_SUMMARY)
    embed.description = _format_grouped_aligned(main_list) if main_list else "참여자 없음"
    return embed


def _count_main(scrim_id: int) -> int:
    """본인 + 대리 합쳐서 정참가자 수."""
    own = sum(1 for _, wl in db.get_participants(scrim_id) if not wl)
    proxy = sum(1 for r in db.get_proxy_participants(scrim_id) if not r["is_waitlist"])
    return own + proxy


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
        self._update_button_state(_count_main(self.scrim_id), scrim["capacity"])
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

        if any(uid == interaction.user.id for uid, _ in db.get_participants(self.scrim_id)):
            await interaction.response.send_message("이미 참가 중입니다.", ephemeral=True)
            return

        main_count_before = _count_main(self.scrim_id)
        as_waitlist = main_count_before >= scrim["capacity"]

        if not db.add_participant(self.scrim_id, interaction.user.id, as_waitlist):
            await interaction.response.send_message("이미 참가 중입니다.", ephemeral=True)
            return

        await self._refresh(interaction)
        if as_waitlist:
            await interaction.followup.send(
                "🕐 정원이 다 차서 **대기자**로 등록되었어요. 자리 비면 자동 승격됩니다.",
                ephemeral=True,
            )

    async def _on_cancel(self, interaction: discord.Interaction):
        scrim = db.get_scrim(self.scrim_id)
        if scrim is None:
            await interaction.response.send_message("모집 정보를 찾을 수 없습니다.", ephemeral=True)
            return

        target_wl = next(
            (wl for uid, wl in db.get_participants(self.scrim_id) if uid == interaction.user.id),
            None,
        )
        if target_wl is None:
            await interaction.response.send_message("참가 중이 아닙니다.", ephemeral=True)
            return

        was_main = (target_wl == 0)
        db.remove_participant(self.scrim_id, interaction.user.id)
        promoted = db.promote_oldest_waitlist(self.scrim_id) if was_main else None

        await self._refresh(interaction)
        if promoted:
            if promoted["type"] == "own":
                msg = f"<@{promoted['user_id']}>님이 대기자에서 참가자로 자동 승격되었어요! 🎉"
            else:
                msg = f"**{promoted['name']}**님(대리)이 대기자에서 참가자로 자동 승격되었어요! 🎉"
            await interaction.followup.send(msg, ephemeral=False)

    async def _on_summary(self, interaction: discord.Interaction):
        scrim = db.get_scrim(self.scrim_id)
        if scrim is None:
            await interaction.response.send_message("모집 정보를 찾을 수 없습니다.", ephemeral=True)
            return

        if _count_main(self.scrim_id) < scrim["capacity"]:
            await interaction.response.send_message(
                f"아직 정원이 안 찼어요 ({_count_main(self.scrim_id)}/{scrim['capacity']})",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        summary = await build_summary_embed(interaction.client, scrim)
        await interaction.channel.send(embed=summary)


async def _refresh_scrim_message(bot: commands.Bot, scrim_row) -> None:
    """모집 메시지를 다시 그려서 업데이트 (슬래시 커맨드에서 사용)."""
    if scrim_row["message_id"] is None:
        return
    channel = bot.get_channel(scrim_row["channel_id"])
    if channel is None:
        return
    try:
        msg = await channel.fetch_message(scrim_row["message_id"])
    except (discord.NotFound, discord.HTTPException):
        return
    is_full = _count_main(scrim_row["scrim_id"]) >= scrim_row["capacity"]
    view = ScrimView(scrim_row["scrim_id"], is_full=is_full)
    embed = await build_embed(bot, scrim_row)
    try:
        await msg.edit(embed=embed, view=view)
    except discord.HTTPException:
        pass


class ScrimCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        rows = db.get_persistent_scrims()
        for row in rows:
            scrim = db.get_scrim(row["scrim_id"])
            is_full = scrim is not None and _count_main(row["scrim_id"]) >= scrim["capacity"]
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

    @app_commands.command(name="대신참가", description="다른 사람 대신 참가시키기 (디스코드 없어도 OK)")
    @app_commands.describe(닉="이름/티어/라인 형식 (예: 홍길동/M350/MID.TOP)")
    async def proxy_join(self, interaction: discord.Interaction, 닉: str):
        if interaction.guild is None:
            await interaction.response.send_message("서버에서만 사용할 수 있습니다.", ephemeral=True)
            return

        parsed = parse_nickname(닉)
        if not parsed.is_valid:
            await interaction.response.send_message(NICK_FORMAT_HELP, ephemeral=True)
            return

        scrim = db.find_latest_open_scrim_in_channel(interaction.channel.id)
        if scrim is None:
            await interaction.response.send_message(
                "이 채널에 모집이 없어요. `/내전모집` 먼저 만들어주세요.",
                ephemeral=True,
            )
            return

        positions_str = ",".join(parsed.positions)
        main_count_before = _count_main(scrim["scrim_id"])
        as_waitlist = main_count_before >= scrim["capacity"]

        ok = db.add_proxy_participant(
            scrim_id=scrim["scrim_id"],
            name=parsed.name,
            tier_raw=parsed.tier_raw,
            positions=positions_str,
            proxy_by_user_id=interaction.user.id,
            is_waitlist=as_waitlist,
        )
        if not ok:
            await interaction.response.send_message(
                f"이미 같은 이름(`{parsed.name}`)이 등록되어 있어요.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"✅ **{parsed.name}** ({parsed.tier_display} / {parsed.positions_display}) "
            f"{'🕐 대기자로 ' if as_waitlist else ''}등록 완료 (대리: <@{interaction.user.id}>)",
            ephemeral=False,
        )
        # 모집 메시지 갱신
        scrim = db.get_scrim(scrim["scrim_id"])
        await _refresh_scrim_message(self.bot, scrim)

    @app_commands.command(name="내전현황", description="현재 모집 명단을 채팅창 아래에 새로 띄우기")
    async def show_status(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("서버에서만 사용할 수 있습니다.", ephemeral=True)
            return

        scrim = db.find_latest_open_scrim_in_channel(interaction.channel.id)
        if scrim is None:
            await interaction.response.send_message(
                "이 채널에 모집이 없어요. `/내전모집` 먼저 만들어주세요.",
                ephemeral=True,
            )
            return

        embed = await build_embed(self.bot, scrim)
        is_full = _count_main(scrim["scrim_id"]) >= scrim["capacity"]
        view = ScrimView(scrim["scrim_id"], is_full=is_full)

        await interaction.response.send_message(embed=embed, view=view)
        msg = await interaction.original_response()
        # 이제 새 메시지가 메인 (참가/취소 시 봇이 갱신할 대상)
        db.set_message_id(scrim["scrim_id"], msg.id)

    @app_commands.command(name="대신취소", description="대리 등록된 사람 취소 (시전자 또는 서버 관리자만)")
    @app_commands.describe(닉="취소할 사람의 이름 (대리 등록 시 사용한 이름)")
    async def proxy_cancel(self, interaction: discord.Interaction, 닉: str):
        if interaction.guild is None:
            await interaction.response.send_message("서버에서만 사용할 수 있습니다.", ephemeral=True)
            return

        scrim = db.find_latest_open_scrim_in_channel(interaction.channel.id)
        if scrim is None:
            await interaction.response.send_message("이 채널에 모집이 없어요.", ephemeral=True)
            return

        is_creator = interaction.user.id == scrim["creator_id"]
        is_admin = (
            isinstance(interaction.user, discord.Member)
            and interaction.user.guild_permissions.administrator
        )
        if not (is_creator or is_admin):
            await interaction.response.send_message(
                "취소는 **모집 시전자** 또는 **서버 관리자**만 가능합니다.",
                ephemeral=True,
            )
            return

        # 대리 등록 여부 확인 (이름으로)
        target = next(
            (r for r in db.get_proxy_participants(scrim["scrim_id"]) if r["name"] == 닉),
            None,
        )
        if target is None:
            await interaction.response.send_message(
                f"`{닉}` 이름으로 대리 등록된 사람이 없어요.",
                ephemeral=True,
            )
            return

        was_main = (target["is_waitlist"] == 0)
        db.remove_proxy_participant(scrim["scrim_id"], 닉)
        promoted = db.promote_oldest_waitlist(scrim["scrim_id"]) if was_main else None

        followup = f"❌ **{닉}** 대리 등록을 취소했어요."
        if promoted:
            if promoted["type"] == "own":
                followup += f"\n→ <@{promoted['user_id']}>님이 대기자에서 자동 승격되었어요! 🎉"
            else:
                followup += f"\n→ **{promoted['name']}**님(대리)이 대기자에서 자동 승격되었어요! 🎉"

        await interaction.response.send_message(followup, ephemeral=False)
        scrim = db.get_scrim(scrim["scrim_id"])
        await _refresh_scrim_message(self.bot, scrim)


async def setup(bot: commands.Bot):
    await bot.add_cog(ScrimCog(bot))
