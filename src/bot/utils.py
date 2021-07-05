import discord


class FakeTarget:
    def __init__(self, guild: discord.Guild) -> None:
        self.guild = guild

    async def send(self, *args, **kwargs) -> None:
        return


def find_target(guild: discord.Guild):
    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).send_messages:
            target = channel
            break

    if target is None:
        target = guild.owner

    if target:
        return target
    else:
        # Return fake object
        return FakeTarget(guild)
