import discord
from discord.ext import commands
from pymongo import MongoClient
from datetime import datetime, timedelta
from linkdb import link_db
from discord import Embed
import random
from emoji import *
import pytz

mongo_client = MongoClient(link_db)
db = mongo_client['wakeup_db']
collection = db['wake_ups']

class gm(commands.Cog):
    def __init__(self, bot:commands.Bot):
        self.bot = bot
        self.collection = MongoClient(link_db)["wakeup_db"]["wake_ups"]
        self.polish_timezone = pytz.timezone('Europe/Warsaw') #Set the correct timezone
        
    @discord.slash_command(description='Śledź swoje wczesne pobudki!')
    async def gm(self, ctx):
        user_id = str(ctx.author.id)
        user_record = self.collection.find_one({'user_id': user_id})
        
        current_time = datetime.utcnow()
        current_time_polish = current_time.astimezone(self.polish_timezone)
        previous_wakeup = user_record['last_wakeup'] if user_record else current_time - timedelta(days=1)
        streak_wakeups = user_record['streak_wakeups'] if user_record else 0
        
        if current_time_polish.date() == previous_wakeup.date():
            await ctx.respond("Za mało kawy? Tylko raz można się obudzić ☕️")
            return
        
        random_message = ["Brawo! Twój wcześniejszy start dnia zasługuje na uznanie! Trzymaj się tego streaku!", "Twoja dyscyplina ranna przynosi efekty! Kontynuuj ten świetny streak!", 
                          "Twój wcześniejszy start to klucz do sukcesu! Bądź dumny, trzymaj się tego streaku!", "Widzę, że zaczynasz dzień od razu! Trzymaj się tego fantastycznego streaku!",
                          "Twoje wcześniejsze przebudzenie jest inspirujące! Kontynuuj ten niesamowity streak!", "Rozpocząłeś dzień z mocą! Trzymaj się tego rannego streaku!",
                          "Twoje wcześniejsze pobudki naprawdę się opłacają! Brawo, trzymaj się tego streaku!", "O świcie jesteś nie do zatrzymania! Trzymaj się tego świetnego streaku!",
                          "Twój ranny start dnia to klucz do sukcesu! Bądź konsekwentny, trzymaj się tego streaku!", "Twoje poranne rutyny przyciągają sukces! Niech ten streak będzie Twoją motywacją!"
                          ]

        if 4 <= current_time_polish.hour < 6:
            if streak_wakeups == 0: #If someone's starting their streak, change it to 1
                streak_wakeups = 1
                
                embed_start = Embed(
                    title='Twoje pobudki!',
                    color=0xa3ffb4
                )
                embed_start.add_field(name='',
                                      value='🙌 Mocny początek! Witaj w swoim rannym streaku, jesteśmy z Tobą!')
                embed_start.add_field(name=f'🌅 Poranki: {streak_wakeups}',
                                      value='',
                                      inline=False)
                if ctx.author.avatar:
                    embed_start.set_thumbnail(url=ctx.author.avatar.url)
                else:
                    embed_start.set_thumbnail(url=ctx.author.default_avatar.url)
                
                reply_message = embed_start
                
            else: #Adds 1 to the streak
                streak_wakeups += 1
                
                embed_streak = Embed(
                    title='Twoje pobudki!',
                    color=0xa3ffb4
                )
                embed_streak.add_field(name='',
                                       value="🙌 " + random.choice(random_message))
                embed_streak.add_field(name='',
                                       value=f'🌅 Poranki: {streak_wakeups}',
                                       inline=False)
                if ctx.author.avatar:
                    embed_streak.set_thumbnail(url=ctx.author.avatar.url)
                else:
                    embed_streak.set_thumbnail(url=ctx.author.default_avatar.url)
                    
                reply_message = embed_streak
                
            self.collection.update_one({'user_id': user_id}, {'$set': {"last_wakeup": current_time, 'streak_wakeups': streak_wakeups}}, upsert=True)
            updated_record = self.collection.find_one({'user_id': user_id})
            streak_wakeups = updated_record['streak_wakeups']
        else:
            reply_message = Embed(
                title='Dzień dobry!',
                color=0xfef65b
            )
            reply_message.add_field(name='',
                                    value=f'🙌 Co dobrego Cię dzisiaj spotka?')
            reply_message.add_field(name=f'🌅 Poranki: {streak_wakeups}',
                                    value='',
                                    inline=False)
            if ctx.author.avatar:
                reply_message.set_thumbnail(url=ctx.author.avatar.url)
            else:
                reply_message.set_thumbnail(url=ctx.author.default_avatar.url)

            streak_wakeups = 0
            self.collection.update_one({'user_id': user_id}, {'$set': {'last_wakeup': current_time, 'streak_wakeups': streak_wakeups}}, upsert=True)
            
        await ctx.respond(embed=reply_message)

def setup(bot:commands.Bot):    
    bot.add_cog(gm(bot))