from typing import Optional
from discord.ext import commands
from ..response import bad, raw_resp
from core.i18n.i18n import _
from tri import atri

class Help(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command()
    async def help(self, ctx: commands.Context, *, command: Optional[str]):
        if command is None:
            embed = raw_resp(
                ctx, 
                text=_("HELP__DESCRIPTION"), 
                title=_("HELP__TITLE")
            )

            for name, cog in self.bot.cogs.items():
                command_names = [
                    f"`{c.qualified_name}`" for c in cog.walk_commands()
                    if (await atri(c.can_run(ctx)))[0] is None
                ]

                if len(command_names) == 0:
                    continue

                embed.add_field(
                    name=f"{name} {getattr(cog, '__badge__', '')}",
                    value=", ".join(command_names)
                )
            
            await ctx.send(embed=embed)
        else:
            cmd = self.bot.get_command(command)
            if cmd is None:
                return await bad(ctx, _("HELP__COMMAND_NOT_FOUND"))
            
            embed = raw_resp(
                ctx, 
                text=cmd.short_doc or _("HELP__COMMAND_DESCRIPTION", name=cmd.qualified_name), 
                title=_("HELP__TITLE")
            )
            
            embed.add_field(
                name=_("HELP__SYNTAX"),
                value=f"{ctx.prefix}{cmd.qualified_name} {cmd.signature}",
                inline=False
            )

            if isinstance(cmd, commands.Group):
                if len(cmd.commands) > 0:
                    command_names = [
                        f"`{c.qualified_name}`" for c in cmd.commands
                    ]

                    embed.add_field(
                        name=_("HELP__SUBCOMMANDS"),
                        value=", ".join(command_names),
                        inline=False
                    )
            
            if len(cmd.parents) > 0:
                command_names = [
                    f"`{c.qualified_name}`" for c in cmd.parents
                ]

                embed.add_field(
                    name=_("HELP__PARENTS"),
                    value=", ".join(command_names),
                    inline=False
                )
            
            await ctx.send(embed=embed)






def setup(bot):
    bot.add_cog(Help(bot))
