from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup, BotCommand
import asyncio
from config import connect_data, admins_ids, BOT_TOKEN
from aiogram.types import FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import asyncpg
import requests
import os


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class Choice(StatesGroup):
    preview_song = State()
    song_link = State()

async def init_pool():
    global pool
    dsn = connect_data
    pool = await asyncpg.create_pool(dsn=dsn)

start_buttons = [
        [KeyboardButton(text='📱 Мой профиль')],
        [KeyboardButton(text='🎵 Найти музыку')],
        [KeyboardButton(text='ℹ Помощь')]
    ]

start_keyboard = ReplyKeyboardMarkup(keyboard=start_buttons, resize_keyboard=True)

choice_buttons = [
        [KeyboardButton(text='🍿 Отрывок')],
        [KeyboardButton(text='🌀 Ссылку')],
    ]

choice_keyboard = ReplyKeyboardMarkup(keyboard=choice_buttons, resize_keyboard=True)


def get_song_info(song: str, request_type: str):

    url = f'https://www.shazam.com/services/amapi/v1/catalog/ru/search?offset=3&term={song}&types=songs&limit=1'
    try:
        response = requests.get(url)
        response = response.json()
        if request_type == 'preview':
            preview = response['results']['songs']['data'][0]['attributes']['previews'][0]['url']
            new_response = requests.get(preview)
            audiopath = f'audio/{song}.m4a'
            with open(audiopath, 'wb') as f:
                f.write(new_response.content)
            result_name = f'{song}.m4a'
            return result_name, audiopath
        else:
            link = response['results']['songs']['data'][0]['attributes']['url']
            return link
    except Exception:
        return None


async def increment_user_searches(user_id: int):
    try:
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    f"UPDATE users SET n_searches = n_searches + 1 WHERE  tg_id = {user_id};")
    except Exception as e:
        print(f"Error incrementing user searches: {e}")


async def setup_bot_commands():
    cmds = [
        BotCommand(command='/start', description='Запустить бота'),
        BotCommand(command='/help', description='Помощь'),
        BotCommand(command='/profile', description='Открыть профиль'),
        BotCommand(command='/search', description='Поиск музыки')
    ]
    await bot.set_my_commands(cmds)


@dp.message(Command('start'))
async def cmd_start(message: Message):
    try:
        async with pool.acquire() as connection:
            async with connection.transaction():
                result = await connection.fetchrow(
                    f"SELECT * FROM users where tg_id = {message.from_user.id}"
                )
                if not(result):
                    await connection.execute(
                    f"""INSERT INTO users (tg_id, first_name, last_name, n_searches) VALUES(
                        {message.from_user.id},
                        '{message.from_user.first_name}',
                        '{message.from_user.last_name}',
                        {0});"""
                    )

    except Exception as e:
        print(e)

    await message.answer('👋 Привет! Я - бот для поиска музыки.', reply_markup=start_keyboard)


@dp.message(Command(commands=['help']))
@dp.message(F.text.lower()=='ℹ помощь')
async def cmd_help(message: Message):
    await message.answer("📌 Отправьте мне название музыкального произведения и получите ссылку на него\n🔎 Если песня не найдена, проверьте правильность написания названия или попробуйте запросить музыкальное произведение с псевдонимом артиста")


@dp.message(Command(commands=['profile']))
@dp.message(F.text.lower()=='📱 мой профиль')
async def cmd_profile(message: Message):
    try:
        async with pool.acquire() as connection:
            async with connection.transaction():
                profile = await connection.fetchrow(
                    f"SELECT * FROM users where tg_id = {message.from_user.id}")
    except Exception as e:
        print(e)

    await message.answer(f'📱 Ваш профиль:\n\n🟢 Имя: {profile["first_name"]}\n🔑 ID: {profile["tg_id"]}\n🎵 Количество поисков: {profile["n_searches"]}',
                        reply_markup=start_keyboard)
    

@dp.message(Command(commands=['search']))
@dp.message(F.text.lower()=='🎵 найти музыку')
async def cmd_search(message: Message):
    await message.answer('❔ Вы хотите получить отрывок трека или ссылку на него в Apple music?', reply_markup=choice_keyboard)


@dp.message(F.text.lower()=='🍿 отрывок')
async def get_preview(message: Message, state: FSMContext):
    await state.set_state(Choice.preview_song)
    await message.answer('⚡ Введите название музыкального произведения')


@dp.message(F.text.lower()=='🌀 ссылку')
async def get_preview(message: Message, state: FSMContext):
    await state.set_state(Choice.song_link)
    await message.answer('⚡ Введите название музыкального произведения')


@dp.message(Choice.preview_song)
async def get_song_preview(message: Message, state: FSMContext):

    await state.update_data(preview_song=message.text)
    data = await state.get_data()
    song = data.get('preview_song')

    request_result = get_song_info(song, "preview")

    if request_result is not None:
        await bot.send_audio(message.chat.id, FSInputFile(request_result[1], filename=request_result[0]), reply_markup=start_keyboard, reply_to_message_id=message.message_id)
    else:
        await message.reply('Песня не найдена', reply_markup=start_keyboard)

    await increment_user_searches(message.from_user.id)

    os.remove(f'audio/{request_result[0]}')

    await state.clear()


@dp.message(Choice.song_link)
async def get_song_link(message: Message, state: FSMContext):

    await state.update_data(song_link=message.text)
    data = await state.get_data()
    song = data.get('song_link')

    link = get_song_info(song, "get link")

    if link is not None:
        await message.reply(link, reply_markup=start_keyboard)
    else:
        await message.reply('Песня не найдена', reply_markup=start_keyboard)

    await increment_user_searches(message.from_user.id)

    await state.clear()


@dp.message(Command(commands=['get_bot_stats']))
async def get_bot_stats(message: Message):
    if message.from_user.id in admins_ids:
        try:
            async with pool.acquire() as connection:
                async with connection.transaction():
                    result = await connection.fetchrow(
                        "SELECT COUNT(*), SUM(n_searches) FROM users;"
                    )
        except Exception as e:
            print(e)
        await message.reply(f'Количество уникальных пользователей бота: {result[0]}\nВсего совершено поисков: {result[1]}', reply_markup=start_keyboard)
    else:
        await message.reply('Извините, я вас не понимаю', reply_markup=start_keyboard)


@dp.message()
async def cmd_error(message=Message):
    await message.reply('Извините, я вас не понимаю', reply_markup=start_keyboard)


async def main():
    await setup_bot_commands()
    await init_pool()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())