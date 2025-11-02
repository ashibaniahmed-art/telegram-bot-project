import telegram
import asyncio

token = "8474550333:AAHEyI-V76fN9SJ7E4JarUsd22F8tU6qR3A"
bot = telegram.Bot(token=token)

async def main():
    async with bot:
        print(await bot.get_me())

if __name__ == "__main__":
    asyncio.run(main())
    


                




