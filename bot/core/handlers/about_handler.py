from aiogram.types import Message

from bot.config_dir.config import env
from bot.core.utils.keyboards import about_kb


async def show_about(message: Message):
    text = env.message_templates.render('message_about', message)
    await message.answer(text, reply_markup=about_kb())