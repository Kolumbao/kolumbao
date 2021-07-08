import asyncio
import uuid
from typing import Union

from discord_components.component import Select, SelectOption
from bot.response import resp

from core.i18n.i18n import _
from discord.ext import commands
from discord_components.interaction import Interaction

async def handle_interaction_end(target: Union[commands.Context, Interaction]):
    await resp(target, _("INTERACTION__CLOSED"))


async def selection(
    bot: commands.Bot,
    target: Union[commands.Context, Interaction],
    choices: Union[list, dict],
    min_values: int = 1,
    max_values: int = 1
):
    if isinstance(choices, list):
        choices = {
            choice: choice
            for choice in choices
        }
    
    send = None
    if isinstance(target, commands.Context):
        send = target.send
    else:
        send = target.respond
   
    await send(
        content=_("INTERACTION__PICK_OPTION"),
        components=[
            Select(
                placeholder=_("INTERACTION__SELECT"),
                options=[
                    *[
                        # All options with choices
                        SelectOption(label=choice, value=choice_id)
                        for choice_id, choice in choices.items()
                    ],
                    SelectOption(label=_("INTERACTION__CLOSE"), value="close"),
                ],
                min_values=min_values,
                max_values=max_values
            )
        ],
        ephemeral=False
    )
    
    interaction = None
    try:
        interaction: Interaction = await bot.wait_for(
            "select_option", check=lambda i: i.user == target.author, timeout=60
        )

        if max_values == 1:
            value = interaction.component[0].value
                
            if value == "close": 
                raise asyncio.TimeoutError()
            
            return value, interaction
        else:
            values = [
                component.value
                for component in interaction.component
            ]

            if "close" in values:
                raise asyncio.TimeoutError()

            return values, interaction
    except asyncio.TimeoutError:
        await handle_interaction_end(interaction or target)
        return None, interaction
