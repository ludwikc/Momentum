import discord
from discord.ext import commands, tasks
import logging

logger = logging.getLogger("momentum_bot.auto_assign_role")

invite_mapping = {
    "4kXt95T53R": "1230797917913223279", 
    "vbvBptbUSk": "1224735643423215776",
    "Gy9MGxyv68": "1232624150418292746"
}

class AutoAssignRole(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.invite_uses = {}
        
    @commands.Cog.listener()
    async def on_ready(self):
        """Start the invite tracking when the bot is ready"""
        logger.info("Starting invite tracking")
        self.update_invites.start()

    def cog_unload(self):
        """Clean up when the cog is unloaded"""
        self.update_invites.cancel()
        logger.info("Invite tracking cancelled")

    @tasks.loop(minutes=1)
    async def update_invites(self):
        """Update the invite cache every minute"""
        try:
            for guild in self.bot.guilds:
                try:
                    current_invites = await guild.invites()
                    self.invite_uses[guild.id] = {invite.code: invite.uses for invite in current_invites}
                    logger.debug(f"Updated invites for {guild.name}")
                except Exception as e:
                    logger.error(f"Failed to update invites for {guild.name}: {e}")
        except Exception as e:
            logger.error(f"Error in update_invites: {e}")
            import traceback
            traceback.print_exc()
                
    @update_invites.before_loop
    async def before_update_invites(self):
        """Wait until the bot is ready before starting the loop."""
        await self.bot.wait_until_ready()
        logger.info("Invite tracking ready to start")

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
