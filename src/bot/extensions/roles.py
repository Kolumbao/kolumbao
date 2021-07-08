# -*- coding: utf-8 -*-
import typing as t

import discord
from discord.ext import commands

from ..checks import has_permission
from ..paginator import EmbedPaginatorSession
from ..response import bad
from ..response import good
from ..response import resp
from core.db import query
from core.db import session
from core.db.models import Permission
from core.db.models import Role
from core.db.utils import get_user
from core.i18n.i18n import _


class Roles(commands.Cog):
    __badge__ = "<:shielddefault:783294498678505512>"
    __badge_success__ = "<:shieldsuccess:783294498776154142>"
    __badge_fail__ = "<:shieldfail:783294498637742091>"

    """
    For i18n:
    _("INSPECT_CHANNELS")
    _("MANAGE_ROLES")
    _("MANAGE_PERMISSIONS")
    _("MANAGE_SNIPPETS")
    _("MANAGE_FEATURES")
    _("MANAGE_WARNS")
    _("MANAGE_MUTES")
    _("MANAGE_LOCKDOWN")
    _("MANAGE_BLACKLISTS")
    _("VIEW_ADVANCED_STATS")
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @has_permission("MANAGE_ROLES")
    @commands.command("get-roles", aliases=["roles"])
    async def get_user_roles(self, ctx, user: discord.User):
        """Get the roles a user has"""
        database_user = get_user(user.id)
        if len(database_user.roles) == 0:
            return await bad(ctx, _("GET_ROLES__NO_ROLES"))

        roles = ", ".join(f"**{role}**" for role in database_user.roles)
        await resp(ctx, _("GET_ROLES__CONTENT", roles=roles))

    @has_permission("MANAGE_ROLES")
    @commands.command("add-role")
    async def add_role(self, ctx, user: discord.User, *, name: str):
        """Add a role to a user"""
        database_user = get_user(user.id)
        role = query(Role).filter(Role.name == name).first()
        if role is None:
            return await bad(ctx, _("ROLE_NOT_FOUND", name=name))

        if role in database_user.roles:
            return await bad(ctx, _("ADD_ROLE__ALREADY_ADDED"))

        database_user.roles.append(role)
        session.commit()

        await good(ctx, _("ADD_ROLE__SUCCESS", role=str(role)))
        self.bot.logger.info(f"Added role {role} to {user} ({user.id})")

    @has_permission("MANAGE_ROLES")
    @commands.command("remove-role")
    async def remove_role(self, ctx, user: discord.User, *, name: str):
        """Take a role from a user"""
        database_user = get_user(user.id)
        role = query(Role).filter(Role.name == name).first()
        if role is None:
            return await bad(ctx, _("ROLE_NOT_FOUND", name=name))

        if role not in database_user.roles:
            return await bad(ctx, _("REMOVE_ROLE__NOT_ADDED"))

        database_user.roles.remove(role)
        session.commit()

        await good(ctx, _("REMOVE_ROLE__SUCCESS", role=str(role)))
        self.bot.logger.info(f"Removed role {role} from {user} ({user.id})")

    @has_permission("MANAGE_ROLES")
    @commands.command("role-info", aliases=["role", "r"])
    async def role_info(self, ctx, *, name: str):
        """Get information about a role"""
        role = query(Role).filter(Role.name == name).first()
        if role is None:
            return await ctx.send(_("ROLE_NOT_FOUND", name=name))

        possible = ""
        if role.staff:
            possible = "<:shieldstaff:783307418159022081> " + _("ROLE_STAFF_NOTICE")

        embed = discord.Embed(title=str(role), description=possible)
        embed.add_field(name=_("ROLE_ID"), value=role.id)
        embed.add_field(name=_("ROLE_NAME"), value=role.name)
        embed.add_field(name=_("ROLE_EMOJI"), value=role.emoji)

        if len(role.users) > 0:
            list_of_users = ""
            for dbuser in role.users:
                list_of_users += f"<@{dbuser.discord_id}> "
            list_of_users = list_of_users or discord.Embed.Empty

            embed.add_field(name=_("ROLE_USERS"), value=list_of_users)

        list_of_permissions = ""
        for permission in role.permissions:
            list_of_permissions += f"- {_(permission)}\n"

        list_of_permissions = list_of_permissions or discord.Embed.Empty

        embed.add_field(name=_("ROLE_PERMISSIONS"), value=list_of_permissions)

        await ctx.send(embed=embed)

    @commands.command("list-roles", aliases=["all-roles"])
    async def list_roles(self, ctx):
        """List all roles"""
        roles = query(Role).all()
        pages = []

        for role in roles:
            possible = ""
            if role.staff:
                possible = "<:shieldstaff:783307418159022081> " + _("ROLE_STAFF_NOTICE")

            page = discord.Embed(title=str(role), description=possible)
            page.add_field(name=_("ROLE_ID"), value=role.id)
            page.add_field(name=_("ROLE_NAME"), value=role.name)
            page.add_field(name=_("ROLE_EMOJI"), value=role.emoji)

            if len(role.users) > 0:
                list_of_users = ""
                for dbuser in role.users:
                    list_of_users += f"<@{dbuser.discord_id}> "
                list_of_users = list_of_users or discord.Embed.Empty
                page.add_field(name=_("ROLE_USERS"), value=list_of_users)

            list_of_permissions = ""
            for permission in role.permissions:
                list_of_permissions += f"- {_(permission)}\n"

            list_of_permissions = list_of_permissions or discord.Embed.Empty
            page.add_field(name=_("ROLE_PERMISSIONS"), value=list_of_permissions)

            pages.append(page)

        pg = EmbedPaginatorSession(ctx, *pages)
        await pg.run()

    @has_permission("MANAGE_ROLES")
    @commands.command("create-role")
    async def create_role(
        self, ctx, name: str, emoji: str, staff: t.Optional[bool] = False
    ):
        """Create a new role"""
        role = query(Role).filter(Role.name == name).first()
        if role is not None:
            return await bad(ctx, _("CREATE_ROLE__ALREADY_EXISTS"))

        role = Role(name=name, emoji=emoji, staff=staff)

        session.add(role)
        session.commit()
        await good(ctx, _("CREATE_ROLE_SUCCESS", id=role.id, role=str(role)))
        self.bot.logger.info(f"Created role {role}, {staff=}")

    @has_permission("MANAGE_ROLES")
    @commands.command("delete-role")
    async def delete_role(self, ctx, name: str):
        """Delete a role"""
        role = query(Role).filter(Role.name == name).first()
        if role is None:
            return await bad(ctx, _("ROLE_NOT_FOUND"))

        session.delete(role)
        session.commit()

        await good(ctx, _("DELETE_ROLE__SUCCESS"))
        self.bot.logger.info(f"Deleted role {role}")

    @has_permission("MANAGE_PERMISSIONS")
    @commands.command("add-role-permission")
    async def add_role_permission(self, ctx, name: str, *permission_names):
        """Add a permission to a role"""
        role = query(Role).filter(Role.name == name).first()
        if role is None:
            return await bad(ctx, _("ROLE_NOT_FOUND"), role=name)

        permissions = []
        user = get_user(ctx.author.id)
        for permission_name in permission_names:
            permission_name = permission_name.upper()
            permission = (
                query(Permission).filter(Permission.name == permission_name).first()
            )
            if permission is None:
                return await bad(ctx, _("PERMISSION_NOT_FOUND", name=permission_name))
            
            if user.has_permissions(permission.name):
                return await bad(
                    ctx,
                    _(
                        "ADD_ROLE_PERMISSION__HEIGHTENED_PERMISSIONS",
                        name=permission_name,
                    ),
                )

            permissions.append(permission)

        role.perms.extend(permissions)
        session.commit()

        await good(
            ctx,
            _(
                "ADD_ROLE_PERMISSION__SUCCESS",
                permissions=", ".join(_(p) for p in role.permissions),
            ),
        )
        self.bot.logger.info(f"Added permissions {permission_names} to {role}")

    @has_permission("MANAGE_PERMISSIONS")
    @commands.command("remove-role-permission")
    async def remove_role_permission(self, ctx, name: str, *permission_names):
        """Remove a permission from a role"""
        role = query(Role).filter(Role.name == name).first()
        if role is None:
            return await bad(ctx, _("ROLE_NOT_FOUND"))

        user = get_user(ctx.author.id)
        for permission_name in permission_names:
            permission_name = permission_name.upper()
            permission = (
                query(Permission).filter(Permission.name == permission_name).first()
            )
            if permission is None:
                return await bad(ctx, _("PERMISSION_NOT_FOUND", name=permission_name))
            
            if user.has_permissions(permission.name):
                return await bad(
                    ctx,
                    _(
                        "REMOVE_ROLE_PERMISSION__HEIGHTENED_PERMISSIONS",
                        name=permission_name,
                    ),
                )

            role.perms.remove(permission)

        session.commit()

        await good(
            ctx,
            _(
                "REMOVE_ROLE_PERMISSION__SUCCESS",
                permissions=", ".join(_(p) for p in role.permissions),
            ),
        )
        self.bot.logger.info(f"Deleted permissions {permission_names} from {role}")

    @has_permission("MANAGE_PERMISSIONS")
    @commands.command("create-permission")
    async def create_permission(self, ctx, name: str.upper):
        """Create a new permission"""
        permission = query(Permission).filter_by(name=name).first()
        if permission is not None:
            return await bad(ctx, _("CREATE_PERMISSION__ALREADY_EXISTS"))

        permission = Permission(name=name)
        session.add(permission)
        session.commit()

        await good(ctx, _("CREATE_PERMISSION__SUCCESS"))
        self.bot.logger.info(f"Created permission {name}")

    @has_permission("MANAGE_PERMISSIONS")
    @commands.command("delete-permission")
    async def delete_permission(self, ctx, name: str.upper):
        """Delete a permission"""
        permission = query(Permission).filter_by(name=name).first()
        if permission is None:
            return await bad(ctx, _("PERMISSION_NOT_FOUND"))

        session.delete(permission)
        session.commit()

        await good(ctx, _("DELETE_PERMISSION__SUCCESS"))
        self.bot.logger.info(f"Deleted permission {name}")

    @has_permission("MANAGE_PERMISSIONS")
    @commands.command("list-permissions")
    async def list_permissions(self, ctx):
        """List permissions"""
        permissions = query(Permission.name).all()

        permissions_list = ", ".join(p[0] for p in permissions)
        await resp(ctx, _("LIST_PERMISSIONS__CONTENT", permissions=permissions_list))


def setup(bot):
    bot.add_cog(Roles(bot))
