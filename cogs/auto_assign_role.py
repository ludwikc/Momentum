import discord
from discord.ext import commands, tasks

invite_mapping = {
    "SbwkfuvY3z": "1232662332258386011",
    "pjqdPsASWZ": "1232662386905972806",
    "qRVf8PVEcn": "1232662420468666440",
}

class AutoAssignRole(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.invite_uses = {}
        self.update_invites.start()

    def cog_unload(self):
        self.update_invites.cancel()

    @tasks.loop(minutes=1)
    async def update_invites(self):
        for guild in self.bot.guilds:
            try:
                current_invites = await guild.invites()
                self.invite_uses[guild.id] = {invite.code: invite.uses for invite in current_invites}
            except Exception as e:
                print(f"Failed to update invites for {guild.name}: {e}")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild_id = member.guild.id
        current_invites = await member.guild.invites()
        new_uses = {invite.code: invite.uses for invite in current_invites}

        used_invite = None
        for invite_code, uses in new_uses.items():
            if uses > self.invite_uses.get(guild_id, {}).get(invite_code, 0):
                used_invite = invite_code
                break

        if used_invite:
            role_id = invite_mapping.get(used_invite)
            if role_id:
                role = discord.utils.get(member.guild.roles, id=int(role_id))
                if role:
                    await member.add_roles(role)
                    print(f"Assigned {role.name} to {member.display_name} ({member.id})")
                else:
                    print(f"Role not found for ID {role_id}")
            else:
                print(f"No role mapping found for invite {used_invite}")

        # Update cache with the latest invite data
        self.invite_uses[guild_id] = new_uses

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        # Optionally update on member remove to keep the cache accurate
        self.invite_uses[member.guild.id] = {invite.code: invite.uses for invite in await member.guild.invites()}

def setup(bot: commands.Bot):
    bot.add_cog(AutoAssignRole(bot))
